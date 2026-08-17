"""Evaluation stage of the offline bark/meow ML prototype.

Compares three classifiers on one labeled unit population:

1. the production DSP heuristic (classifier-only and full detect-only),
2. zero-shot AST decisions read straight from the AudioSet logits, and
3. a learned head (logistic regression, optionally an MLP) on the frozen
   768-dim AST embeddings, scored out-of-fold under leave-one-recording-out CV.

torch/transformers are never imported here: embeddings and logits are read from
the npz cache written by extract_embeddings.py. scikit-learn and matplotlib live
in the opt-in `ml` group and are imported lazily inside the functions that use
them, so this module imports (and its CSV/npz/report helpers are testable) with
only numpy + meowdb present.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

# The prototype dir is not a package; put it on the path so `import common` works
# no matter the cwd (script run, `-m`, or imported by a throwaway test harness).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

# --- AudioSet-527 class indices for this checkpoint --------------------------
# Defaults follow the AudioSet-527 ontology as ordered by the
# MIT/ast-finetuned-audioset-10-10-0.4593 label map. Hardcoded (rather than
# resolved via common.audioset_target_indices) because that resolver has to load
# the torch model, and this stage must stay torch-free. Override the CLI flags if
# a future checkpoint reorders its labels.
AUDIOSET_INDEX = {
    "Speech": 0,
    "Domestic animals, pets": 73,
    "Dog": 74,
    "Bark": 75,
    "Cat": 81,
    "Meow": 83,
}
DEFAULT_TARGET_INDEX = {"dog": AUDIOSET_INDEX["Bark"], "cat": AUDIOSET_INDEX["Meow"]}
# Competing classes the zero-shot argmax decision chooses among, one of which is
# the target. Speech, Dog, Cat, Bark, Meow — the target is removed at parse time.
DEFAULT_COMPETITOR_INDICES = [
    AUDIOSET_INDEX["Speech"],
    AUDIOSET_INDEX["Dog"],
    AUDIOSET_INDEX["Cat"],
    AUDIOSET_INDEX["Bark"],
    AUDIOSET_INDEX["Meow"],
]

EMBED_DIM = 768
LOGITS_DIM = 527

# npz keys written by extract_embeddings.py (np.savez(embedding=, zeroshot_logits=)).
# Alternates are tried after the canonical name so a future rename surfaces as a
# clear error instead of a silently wrong array.
_EMBED_KEYS = ("embedding", "X", "embeddings", "emb")
_LOGITS_KEYS = ("zeroshot_logits", "logits", "y", "scores")

LEARNING_CURVE_SIZES: tuple[int | str, ...] = (10, 25, 50, "all")
HIGH_PRECISION_TARGET = 0.95


# --- data model --------------------------------------------------------------
@dataclass(frozen=True)
class Unit:
    """One labeled candidate clip."""

    unit_id: str
    source_recording: str
    source_kind: str
    species: str
    label: str
    split_group: str


@dataclass
class Dataset:
    units: list[Unit]
    X: np.ndarray  # (n, 768) float32 embeddings, unit order
    logits: np.ndarray  # (n, 527) float32 AudioSet logits, unit order
    y_binary: np.ndarray  # (n,) bool, True == positive label
    groups: np.ndarray  # (n,) object, split_group per unit

    @property
    def n(self) -> int:
        return len(self.units)


@dataclass
class HeadResult:
    """Out-of-fold learned-head outcome for one estimator kind."""

    name: str
    oof_prob: np.ndarray  # (n,) float, nan where a fold was skipped
    predicted_mask: np.ndarray  # (n,) bool, True where oof_prob is valid
    skipped_units: list[str]


# --- CSV / cache loading -----------------------------------------------------
def load_labels(path: Path, species: str) -> list[Unit]:
    """Read labels.csv, keeping only rows for `species` with a non-blank label."""
    if not path.exists():
        raise FileNotFoundError(f"labels CSV not found: {path} (run prepare_data first)")
    units: list[Unit] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in common.LABELS_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"labels CSV missing columns {missing}; got {reader.fieldnames}")
        for row in reader:
            if (row.get("species") or "").strip() != species:
                continue
            label = (row.get("label") or "").strip()
            if not label:  # un-hand-labeled raw rows are left blank; skip them
                continue
            units.append(
                Unit(
                    unit_id=(row["unit_id"] or "").strip(),
                    source_recording=(row.get("source_recording") or "").strip(),
                    source_kind=(row.get("source_kind") or "").strip(),
                    species=species,
                    label=label,
                    split_group=(row.get("split_group") or "").strip(),
                )
            )
    if not units:
        raise ValueError(f"no labeled {species} rows in {path}; hand-label some units first")
    labels_present = {u.label for u in units}
    if len(labels_present) < 2:
        raise ValueError(
            f"need at least 2 distinct labels for {species}, found {sorted(labels_present)}"
        )
    # Deterministic order downstream: sort by unit_id once, here.
    units.sort(key=lambda u: u.unit_id)
    return units


def load_manifest(path: Path) -> dict[str, str]:
    """Map unit_id -> content_hash from the embeddings manifest."""
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}; run extract_embeddings first")
    mapping: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if "unit_id" not in fields or "content_hash" not in fields:
            raise ValueError(f"manifest must have unit_id,content_hash columns; got {fields}")
        for row in reader:
            uid = (row.get("unit_id") or "").strip()
            chash = (row.get("content_hash") or "").strip()
            if uid:
                mapping[uid] = chash
    return mapping


def _pick_array(npz: Any, keys: Sequence[str], expected_dim: int, unit_id: str) -> np.ndarray:
    """Return the first present key raveled to (expected_dim,) float32."""
    for key in keys:
        if key in npz.files:
            arr = np.asarray(npz[key], dtype=np.float32).reshape(-1)
            if arr.shape[0] != expected_dim:
                raise ValueError(
                    f"{unit_id}: npz[{key!r}] has {arr.shape[0]} values, expected {expected_dim}"
                )
            return arr
    raise KeyError(f"{unit_id}: npz has none of {list(keys)}; found {list(npz.files)}")


def load_unit_cache(cache_dir: Path, content_hash: str, unit_id: str) -> tuple[np.ndarray, np.ndarray]:
    """Load one unit's (embedding (768,), logits (527,)) from CACHE_DIR."""
    npz_path = cache_dir / f"{content_hash}.npz"
    if not npz_path.exists():
        raise FileNotFoundError(
            f"cache miss for {unit_id} ({npz_path.name}); run extract_embeddings first"
        )
    with np.load(npz_path) as npz:
        emb = _pick_array(npz, _EMBED_KEYS, EMBED_DIM, unit_id)
        logits = _pick_array(npz, _LOGITS_KEYS, LOGITS_DIM, unit_id)
    return emb, logits


def assemble_dataset(labels_path: Path, species: str) -> Dataset:
    """Join labels + manifest + npz cache into aligned arrays (unit-id order)."""
    units = load_labels(labels_path, species)
    manifest = load_manifest(common.MANIFEST_CSV)
    positive = common.POSITIVE_LABEL[species]

    unhashed = [u.unit_id for u in units if u.unit_id not in manifest]
    if unhashed:
        preview = ", ".join(unhashed[:5])
        raise ValueError(
            f"{len(unhashed)} labeled units absent from manifest (e.g. {preview}); "
            "run extract_embeddings first"
        )

    embeds = np.empty((len(units), EMBED_DIM), dtype=np.float32)
    logits = np.empty((len(units), LOGITS_DIM), dtype=np.float32)
    for i, unit in enumerate(units):
        emb, log = load_unit_cache(common.CACHE_DIR, manifest[unit.unit_id], unit.unit_id)
        embeds[i] = emb
        logits[i] = log

    y_binary = np.array([u.label == positive for u in units], dtype=bool)
    groups = np.array([u.split_group for u in units], dtype=object)
    return Dataset(units=units, X=embeds, logits=logits, y_binary=y_binary, groups=groups)


# --- training-free baselines -------------------------------------------------
def heuristic_verdicts(units: Sequence[Unit], species: str) -> tuple[np.ndarray, np.ndarray]:
    """Per-unit (classifier-only, detect-only) accept booleans from production DSP."""
    clf_only = np.empty(len(units), dtype=bool)
    detect = np.empty(len(units), dtype=bool)
    for i, unit in enumerate(units):
        wav = common.UNITS_DIR / f"{unit.unit_id}.wav"
        clf_only[i] = common.heuristic_verdict(wav, species)
        detect[i] = common.detect_only_verdict(wav, species)
    return clf_only, detect


def zeroshot_scores(
    logits: np.ndarray, target_index: int, competitor_indices: Sequence[int]
) -> tuple[np.ndarray, np.ndarray]:
    """Return (target-class probability per unit, argmax-over-target-set accept).

    Decision A reads prob[target_index] (threshold swept later). Decision B accepts
    iff the target index is the argmax of probabilities restricted to
    {target} u competitors.
    """
    probs = np.vstack([common.zeroshot_probs(row) for row in logits])  # (n, 527)
    target_prob = probs[:, target_index].astype(np.float64)
    candidate_indices = [target_index, *competitor_indices]
    subset = probs[:, candidate_indices]  # (n, k), column 0 is the target
    argmax_accept = subset.argmax(axis=1) == 0
    return target_prob, argmax_accept


# --- cross-validation --------------------------------------------------------
def _make_logreg(seed: int) -> Any:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    # class_weight balanced: positives are the minority in a candidate population,
    # so weight classes inversely to frequency rather than resampling.
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "clf",
                LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed),
            ),
        ]
    )


def _make_mlp(seed: int) -> Any:
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("clf", MLPClassifier(hidden_layer_sizes=(64,), max_iter=2000, random_state=seed)),
        ]
    )


def _positive_column(estimator: Any) -> int:
    """Column of predict_proba corresponding to the positive (True) class."""
    classes = list(estimator.named_steps["clf"].classes_)
    return classes.index(True)


def _choose_splits(
    y: np.ndarray, groups: np.ndarray, seed: int
) -> tuple[list[tuple[np.ndarray, np.ndarray]], str]:
    """Yield (train_idx, test_idx) folds and a human-readable scheme description.

    LeaveOneGroupOut when >=3 recordings; otherwise StratifiedKFold with a warning
    (LORO is meaningless with one or two recordings).
    """
    from sklearn.model_selection import LeaveOneGroupOut, StratifiedKFold

    n_groups = len(np.unique(groups))
    if n_groups >= 3:
        splitter = LeaveOneGroupOut()
        folds = list(splitter.split(y, y, groups))
        return folds, f"leave-one-recording-out ({n_groups} folds)"

    _, counts = np.unique(y, return_counts=True)
    min_class = int(counts.min())
    n_splits = min(5, min_class)
    if n_splits < 2:
        raise ValueError(
            f"cannot cross-validate: smallest class has {min_class} example(s); need >= 2"
        )
    print(
        f"WARNING: only {n_groups} recording group(s); leave-one-recording-out is "
        f"meaningless, falling back to StratifiedKFold({n_splits})."
    )
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    folds = list(splitter.split(y, y))
    return folds, f"stratified {n_splits}-fold (only {n_groups} recording group(s))"


def cross_val_head(
    dataset: Dataset,
    folds: Sequence[tuple[np.ndarray, np.ndarray]],
    make_estimator: Callable[[int], Any],
    name: str,
    seed: int,
) -> HeadResult:
    """Accumulate out-of-fold predict_proba for the positive class per unit."""
    oof = np.full(dataset.n, np.nan, dtype=np.float64)
    skipped: list[str] = []
    for train_idx, test_idx in folds:
        if len(np.unique(dataset.y_binary[train_idx])) < 2:
            skipped.extend(dataset.units[i].unit_id for i in test_idx)
            continue
        est = make_estimator(seed)
        est.fit(dataset.X[train_idx], dataset.y_binary[train_idx])
        pos_col = _positive_column(est)
        oof[test_idx] = est.predict_proba(dataset.X[test_idx])[:, pos_col]
    if skipped:
        print(
            f"WARNING: {name}: {len(skipped)} unit(s) unpredicted (single-class training folds); "
            "excluded from head metrics."
        )
    predicted = ~np.isnan(oof)
    return HeadResult(
        name=name, oof_prob=oof, predicted_mask=predicted, skipped_units=sorted(skipped)
    )


# --- learning curve ----------------------------------------------------------
def learning_curve(
    dataset: Dataset,
    folds: Sequence[tuple[np.ndarray, np.ndarray]],
    seed: int,
) -> dict[str, dict[str, float]]:
    """Per training size, mean/std of binary P/R/F1 across folds (logreg head).

    Within each fold's training split, positives are subsampled to `n` (all
    negatives kept). A size is skipped for a fold whose training split has fewer
    than `n` positives; "all" uses every positive. Evaluation is at threshold 0.5
    on the held-out fold.
    """
    result: dict[str, dict[str, float]] = {}
    for size in LEARNING_CURVE_SIZES:
        precisions: list[float] = []
        recalls: list[float] = []
        f1s: list[float] = []
        for fold_idx, (train_idx, test_idx) in enumerate(folds):
            y_train = dataset.y_binary[train_idx]
            pos_local = np.where(y_train)[0]
            neg_local = np.where(~y_train)[0]
            if len(pos_local) == 0 or len(neg_local) == 0:
                continue  # degenerate training split
            if isinstance(size, int):
                if len(pos_local) < size:
                    continue
                # Deterministic per (fold, size): child seed from the base seed.
                rng = np.random.default_rng([seed, fold_idx, size])
                chosen_pos = rng.choice(pos_local, size=size, replace=False)
            else:
                chosen_pos = pos_local
            sub_local = np.concatenate([chosen_pos, neg_local])
            sub_idx = train_idx[sub_local]
            if len(np.unique(dataset.y_binary[sub_idx])) < 2:
                continue
            est = _make_logreg(seed)
            est.fit(dataset.X[sub_idx], dataset.y_binary[sub_idx])
            y_pred = est.predict(dataset.X[test_idx]).astype(bool)
            counts = binary_counts(dataset.y_binary[test_idx], y_pred)
            metrics = metrics_from_counts(counts)
            precisions.append(metrics["precision"])
            recalls.append(metrics["recall"])
            f1s.append(metrics["f1"])
        key = "all" if size == "all" else str(size)
        result[key] = _aggregate(precisions, recalls, f1s)
    return result


def _aggregate(
    precisions: list[float], recalls: list[float], f1s: list[float]
) -> dict[str, float]:
    if not f1s:
        nan = float("nan")
        # n_folds stays an integer 0 so the report table can int() it; the scores
        # are nan (rendered as "-", skipped by the plot and the verdict).
        return {
            "precision_mean": nan, "precision_std": nan,
            "recall_mean": nan, "recall_std": nan,
            "f1_mean": nan, "f1_std": nan, "n_folds": 0.0,
        }
    return {
        "precision_mean": float(np.mean(precisions)),
        "precision_std": float(np.std(precisions)),
        "recall_mean": float(np.mean(recalls)),
        "recall_std": float(np.std(recalls)),
        "f1_mean": float(np.mean(f1s)),
        "f1_std": float(np.std(f1s)),
        "n_folds": float(len(f1s)),
    }


# --- metrics -----------------------------------------------------------------
def binary_counts(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, int]:
    """TP/FP/FN/TN for boolean arrays (no sklearn — exact and testable)."""
    yt = y_true.astype(bool)
    yp = y_pred.astype(bool)
    return {
        "tp": int(np.sum(yp & yt)),
        "fp": int(np.sum(yp & ~yt)),
        "fn": int(np.sum(~yp & yt)),
        "tn": int(np.sum(~yp & ~yt)),
    }


def metrics_from_counts(counts: dict[str, int]) -> dict[str, float]:
    """Precision/recall/F1 with zero-division guarded to 0.0."""
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


# --- threshold selection -----------------------------------------------------
@dataclass
class OperatingPoint:
    system: str
    max_f1_threshold: float | None
    high_precision_threshold: float | None
    high_precision_recall: float | None


def pr_curve(y_true: np.ndarray, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from sklearn.metrics import precision_recall_curve

    precision, recall, thresholds = precision_recall_curve(y_true.astype(int), scores)
    return precision, recall, thresholds


def select_operating_points(
    system: str, y_true: np.ndarray, scores: np.ndarray
) -> tuple[OperatingPoint, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Max-F1 threshold and highest-recall threshold at precision >= 0.95."""
    precision, recall, thresholds = pr_curve(y_true, scores)
    # precision/recall have one more entry than thresholds; the trailing point
    # (recall 0) has no threshold, so align to the first len(thresholds) entries.
    p = precision[: len(thresholds)]
    r = recall[: len(thresholds)]
    denom = p + r
    f1 = np.where(denom > 0, 2 * p * r / np.where(denom > 0, denom, 1.0), 0.0)
    max_f1_threshold = float(thresholds[int(np.argmax(f1))]) if len(thresholds) else None

    hp_threshold: float | None = None
    hp_recall: float | None = None
    eligible = np.where(p >= HIGH_PRECISION_TARGET)[0]
    if len(eligible):
        best = eligible[int(np.argmax(r[eligible]))]
        hp_threshold = float(thresholds[best])
        hp_recall = float(r[best])
    point = OperatingPoint(system, max_f1_threshold, hp_threshold, hp_recall)
    return point, (precision, recall, thresholds)


# --- plots -------------------------------------------------------------------
def _init_matplotlib() -> None:
    """Select the headless Agg backend before pyplot is imported anywhere."""
    import matplotlib

    matplotlib.use("Agg")


def _new_axes() -> tuple[Any, Any]:
    import matplotlib.pyplot as plt

    return plt.subplots(figsize=(7, 5))


def plot_learning_curve(curve: dict[str, dict[str, float]], out_path: Path) -> None:
    import matplotlib.pyplot as plt

    xs: list[float] = []
    labels: list[str] = []
    f1_mean: list[float] = []
    f1_std: list[float] = []
    p_mean: list[float] = []
    r_mean: list[float] = []
    for i, key in enumerate([k for k in ("10", "25", "50", "all") if k in curve]):
        stats = curve[key]
        if np.isnan(stats["f1_mean"]):
            continue
        xs.append(float(i))
        labels.append(key)
        f1_mean.append(stats["f1_mean"])
        f1_std.append(stats["f1_std"])
        p_mean.append(stats["precision_mean"])
        r_mean.append(stats["recall_mean"])

    fig, ax = _new_axes()
    if xs:
        f1m = np.array(f1_mean)
        f1s = np.array(f1_std)
        ax.plot(xs, f1m, marker="o", color="#1f77b4", label="F1 (mean)")
        ax.fill_between(xs, f1m - f1s, f1m + f1s, color="#1f77b4", alpha=0.2, label="F1 +/-1 std")
        ax.plot(xs, p_mean, marker=".", color="#2ca02c", alpha=0.6, label="precision (mean)")
        ax.plot(xs, r_mean, marker=".", color="#d62728", alpha=0.6, label="recall (mean)")
        ax.set_xticks(xs)
        ax.set_xticklabels(labels)
    ax.set_ylim(0.0, 1.05)
    ax.set_xlabel("positive training examples per fold")
    ax.set_ylabel("score")
    ax.set_title("Learning curve (logistic-regression head)")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_threshold_sweep(
    head_curve: tuple[np.ndarray, np.ndarray, np.ndarray],
    zeroshot_curve: tuple[np.ndarray, np.ndarray, np.ndarray],
    heuristic_point: tuple[float, float],
    out_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    fig, ax = _new_axes()
    hp, hr, _ = head_curve
    zp, zr, _ = zeroshot_curve
    ax.plot(hr, hp, color="#1f77b4", label="learned head (out-of-fold)")
    ax.plot(zr, zp, color="#ff7f0e", label="zero-shot target prob")
    ax.scatter(
        [heuristic_point[1]], [heuristic_point[0]],
        color="#d62728", zorder=5, label="heuristic (classifier-only)",
    )
    ax.set_xlim(0.0, 1.02)
    ax.set_ylim(0.0, 1.02)
    ax.set_xlabel("recall")
    ax.set_ylabel("precision")
    ax.set_title("Precision-recall sweep")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# --- report rendering --------------------------------------------------------
def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join([head, sep, *body])


def _counts_table(pairs: Sequence[tuple[str, int]]) -> str:
    return _markdown_table(["key", "count"], [[k, v] for k, v in pairs])


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "-"
    return f"{value:.{digits}f}"


def build_results_table(summary_rows: Sequence[dict[str, Any]]) -> str:
    headers = ["system", "threshold", "TP", "FP", "FN", "TN", "precision", "recall", "F1"]
    rows = [
        [
            r["system"],
            _fmt(r["threshold"]) if r["threshold"] is not None else "-",
            r["tp"], r["fp"], r["fn"], r["tn"],
            _fmt(r["precision"]), _fmt(r["recall"]), _fmt(r["f1"]),
        ]
        for r in summary_rows
    ]
    return _markdown_table(headers, rows)


def build_learning_curve_table(curve: dict[str, dict[str, float]]) -> str:
    headers = ["n positives", "F1 mean", "F1 std", "precision mean", "recall mean", "folds"]
    rows = []
    for key in ("10", "25", "50", "all"):
        if key not in curve:
            continue
        s = curve[key]
        rows.append([
            key, _fmt(s["f1_mean"]), _fmt(s["f1_std"]),
            _fmt(s["precision_mean"]), _fmt(s["recall_mean"]), int(s["n_folds"]),
        ])
    return _markdown_table(headers, rows)


def learning_curve_verdict(curve: dict[str, dict[str, float]]) -> str:
    available = [k for k in ("10", "25", "50", "all") if k in curve
                 and not np.isnan(curve[k]["f1_mean"])]
    if len(available) < 2:
        return "Not enough training sizes produced a valid fold to draw a learning-curve verdict."
    small, large = available[0], available[-1]
    f_small = curve[small]["f1_mean"]
    f_large = curve[large]["f1_mean"]
    delta = f_large - f_small
    if delta >= 0.05:
        trend = f"rises {delta:.3f} in mean F1"
    elif delta <= -0.05:
        trend = f"drops {abs(delta):.3f} in mean F1"
    else:
        trend = f"is flat (delta {delta:+.3f} F1)"
    return (
        f"Going from {small} to {large} positives per fold, the head {trend} "
        f"({f_small:.3f} -> {f_large:.3f}), indicating "
        + ("more labeled positives still help." if delta >= 0.05 else
           "the head has roughly saturated on this data.")
    )


def build_operating_points_table(points: Sequence[OperatingPoint]) -> str:
    headers = ["system", "max-F1 threshold", "P>=0.95 threshold", "recall at P>=0.95"]
    rows = [
        [p.system, _fmt(p.max_f1_threshold), _fmt(p.high_precision_threshold),
         _fmt(p.high_precision_recall)]
        for p in points
    ]
    return _markdown_table(headers, rows)


def build_failure_analysis(
    dataset: Dataset, eval_mask: np.ndarray, system_preds: dict[str, np.ndarray]
) -> str:
    """Per system, capped lists of false accepts and false rejects."""
    label_by_id = {u.unit_id: u.label for u in dataset.units}
    unit_ids = np.array([u.unit_id for u in dataset.units], dtype=object)
    blocks: list[str] = []
    for system in sorted(system_preds):
        pred = system_preds[system]
        fa_idx = np.where(eval_mask & pred & ~dataset.y_binary)[0]
        fr_idx = np.where(eval_mask & ~pred & dataset.y_binary)[0]
        fa = sorted(unit_ids[fa_idx].tolist())[:20]
        fr = sorted(unit_ids[fr_idx].tolist())[:20]
        fa_txt = ", ".join(f"`{u}` ({label_by_id[u]})" for u in fa) or "none"
        fr_txt = ", ".join(f"`{u}` ({label_by_id[u]})" for u in fr) or "none"
        blocks.append(
            f"### {system}\n\n"
            f"- False accepts ({len(fa_idx)}): {fa_txt}\n"
            f"- False rejects ({len(fr_idx)}): {fr_txt}"
        )
    return "\n\n".join(blocks)


def render_report(template_path: Path, context: dict[str, Any]) -> str:
    template = template_path.read_text(encoding="utf-8")
    return template.format(**context)


# --- orchestration -----------------------------------------------------------
def parse_competitors(raw: str, target_index: int) -> list[int]:
    indices = [int(tok) for tok in raw.split(",") if tok.strip() != ""]
    # Deduplicate preserving order and drop the target (it is added back as the
    # reference column in the argmax decision).
    seen: set[int] = set()
    result: list[int] = []
    for idx in indices:
        if idx == target_index or idx in seen:
            continue
        seen.add(idx)
        result.append(idx)
    return result


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--species", choices=("dog", "cat"), default="dog")
    parser.add_argument("--labels", type=Path, default=common.LABELS_CSV)
    parser.add_argument("--head", choices=("logreg", "mlp", "both"), default="logreg")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--target-index", type=int, default=None,
        help="AudioSet index of the positive class (default: 75 dog/Bark, 83 cat/Meow).",
    )
    parser.add_argument(
        "--competitor-indices", type=str, default="0,74,81,75,83",
        help="Comma AudioSet indices the argmax decision competes over; target removed.",
    )
    return parser


def _system_predictions(
    dataset: Dataset,
    eval_mask: np.ndarray,
    clf_only: np.ndarray,
    detect: np.ndarray,
    zs_argmax: np.ndarray,
    zs_target_prob: np.ndarray,
    zs_threshold: float | None,
    heads: dict[str, HeadResult],
    head_thresholds: dict[str, float | None],
) -> dict[str, np.ndarray]:
    """Boolean prediction vector per system (only meaningful under eval_mask)."""
    preds: dict[str, np.ndarray] = {
        "heuristic (classifier-only)": clf_only,
        "heuristic (detect-only)": detect,
        "zero-shot (argmax)": zs_argmax,
    }
    if zs_threshold is not None:
        preds["zero-shot (max-F1)"] = zs_target_prob >= zs_threshold
    for name, head in heads.items():
        prob = np.where(head.predicted_mask, head.oof_prob, -np.inf)
        preds[f"{name} (@0.5)"] = prob >= 0.5
        thr = head_thresholds.get(name)
        if thr is not None:
            preds[f"{name} (max-F1)"] = prob >= thr
    return preds


def _summary_rows(
    dataset: Dataset,
    eval_mask: np.ndarray,
    system_preds: dict[str, np.ndarray],
    thresholds: dict[str, float | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    y_eval = dataset.y_binary[eval_mask]
    for system in sorted(system_preds):
        counts = binary_counts(y_eval, system_preds[system][eval_mask])
        metrics = metrics_from_counts(counts)
        rows.append({
            "system": system,
            "threshold": thresholds.get(system),
            **counts,
            **metrics,
        })
    return rows


def main(argv: Sequence[str] | None = None) -> None:
    args = build_argument_parser().parse_args(argv)
    random.seed(args.seed)
    np.random.seed(args.seed)
    _init_matplotlib()  # before any pyplot import in the plotting helpers
    common.ensure_dirs()

    species = args.species
    target_index = (
        args.target_index if args.target_index is not None
        else DEFAULT_TARGET_INDEX[species]
    )
    competitor_indices = parse_competitors(args.competitor_indices, target_index)

    dataset = assemble_dataset(args.labels, species)
    n_pos = int(dataset.y_binary.sum())
    n_neg = int((~dataset.y_binary).sum())
    print(f"Loaded {dataset.n} labeled {species} units ({n_pos} positive, {n_neg} negative).")

    # Training-free baselines over all units.
    clf_only, detect = heuristic_verdicts(dataset.units, species)
    zs_target_prob, zs_argmax = zeroshot_scores(dataset.logits, target_index, competitor_indices)

    # Cross-validated learned head(s). logreg is always trained: it drives the
    # learning curve and the threshold-sweep PR curve. --head selects which heads
    # appear in the metrics table / failure analysis.
    folds, cv_scheme = _choose_splits(dataset.y_binary, dataset.groups, args.seed)
    logreg = cross_val_head(dataset, folds, _make_logreg, "logreg", args.seed)
    # logreg is always reported (and always drives the plots); mlp is added on top
    # when --head is mlp or both.
    heads: dict[str, HeadResult] = {"logreg": logreg}
    if args.head in ("mlp", "both"):
        heads["mlp"] = cross_val_head(dataset, folds, _make_mlp, "mlp", args.seed)

    # Shared evaluation set: units the head could score out-of-fold. Every system
    # is measured on this identical set so differences reflect the classifier.
    eval_mask = logreg.predicted_mask
    n_eval = int(eval_mask.sum())
    n_unpredicted = dataset.n - n_eval
    if n_eval == 0:
        raise ValueError("no units received an out-of-fold head prediction; check the folds")
    if len(np.unique(dataset.y_binary[eval_mask])) < 2:
        raise ValueError(
            "evaluation set (head-scored units) has a single class; "
            "cannot compute a precision-recall sweep"
        )

    # Learning curve + threshold sweep (logreg head).
    curve = learning_curve(dataset, folds, args.seed)
    plot_learning_curve(curve, common.RESULTS_DIR / "learning_curve.png")

    y_eval = dataset.y_binary[eval_mask]
    head_point, head_curve = select_operating_points(
        "learned head", y_eval, logreg.oof_prob[eval_mask]
    )
    zs_point, zs_curve = select_operating_points(
        "zero-shot", y_eval, zs_target_prob[eval_mask]
    )
    heuristic_counts = binary_counts(y_eval, clf_only[eval_mask])
    heuristic_metrics = metrics_from_counts(heuristic_counts)
    plot_threshold_sweep(
        head_curve, zs_curve,
        (heuristic_metrics["precision"], heuristic_metrics["recall"]),
        common.RESULTS_DIR / "threshold_sweep.png",
    )

    # Per-head max-F1 thresholds (each head's own OOF PR curve).
    head_thresholds: dict[str, float | None] = {}
    for name, head in heads.items():
        point, _ = select_operating_points(name, y_eval, head.oof_prob[eval_mask])
        head_thresholds[name] = point.max_f1_threshold

    system_preds = _system_predictions(
        dataset, eval_mask, clf_only, detect, zs_argmax, zs_target_prob,
        zs_point.max_f1_threshold, heads, head_thresholds,
    )
    thresholds: dict[str, float | None] = {
        "heuristic (classifier-only)": None,
        "heuristic (detect-only)": None,
        "zero-shot (argmax)": None,
    }
    if zs_point.max_f1_threshold is not None:
        thresholds["zero-shot (max-F1)"] = zs_point.max_f1_threshold
    for name in heads:
        thresholds[f"{name} (@0.5)"] = 0.5
        if head_thresholds.get(name) is not None:
            thresholds[f"{name} (max-F1)"] = head_thresholds[name]

    summary_rows = _summary_rows(dataset, eval_mask, system_preds, thresholds)

    # --- write outputs -------------------------------------------------------
    label_counts = sorted(
        {lbl: sum(u.label == lbl for u in dataset.units) for lbl in {u.label for u in dataset.units}}.items()
    )
    source_kind_counts = sorted(
        {sk: sum(u.source_kind == sk for u in dataset.units) for sk in {u.source_kind for u in dataset.units}}.items()
    )
    n_library = sum(1 for u in dataset.units if u.source_kind == "library")
    n_raw = dataset.n - n_library
    n_groups = len(np.unique(dataset.groups))

    write_summary_csv(common.RESULTS_DIR / "summary.csv", summary_rows)
    write_metrics_json(
        common.RESULTS_DIR / "metrics.json",
        species=species, seed=args.seed, head_flag=args.head, cv_scheme=cv_scheme,
        target_index=target_index, competitor_indices=competitor_indices,
        n_units=dataset.n, n_positive=n_pos, n_negative=n_neg,
        n_eval_units=n_eval, n_unpredicted=n_unpredicted, n_groups=n_groups,
        label_counts=label_counts, source_kind_counts=source_kind_counts,
        summary_rows=summary_rows, thresholds=thresholds,
        learning_curve=curve, operating_points=[head_point, zs_point],
        skipped_units={name: h.skipped_units for name, h in heads.items()},
    )

    context = {
        "species": species,
        "positive_label": common.POSITIVE_LABEL[species],
        "checkpoint": common.AST_CHECKPOINT,
        "seed": args.seed,
        "head_flag": args.head,
        "cv_scheme": cv_scheme,
        "n_units": dataset.n,
        "n_positive": n_pos,
        "n_negative": n_neg,
        "n_eval_units": n_eval,
        "n_unpredicted": n_unpredicted,
        "n_groups": n_groups,
        "n_library": n_library,
        "n_raw": n_raw,
        "label_counts_table": _counts_table(label_counts),
        "source_kind_table": _counts_table(source_kind_counts),
        "results_table": build_results_table(summary_rows),
        "learning_curve_image": "![learning curve](learning_curve.png)",
        "learning_curve_table": build_learning_curve_table(curve),
        "learning_curve_verdict": learning_curve_verdict(curve),
        "threshold_sweep_image": "![threshold sweep](threshold_sweep.png)",
        "operating_points_table": build_operating_points_table([head_point, zs_point]),
        "failure_analysis": build_failure_analysis(dataset, eval_mask, system_preds),
    }
    report = render_report(common.PROTO_DIR / "report_template.md", context)
    (common.RESULTS_DIR / "report.md").write_text(report, encoding="utf-8")
    print(f"Wrote report, metrics.json, summary.csv, and 2 plots to {common.RESULTS_DIR}")


def write_summary_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fields = ["system", "threshold", "tp", "fp", "fn", "tn", "precision", "recall", "f1"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "system": row["system"],
                "threshold": "" if row["threshold"] is None else f"{row['threshold']:.6f}",
                "tp": row["tp"], "fp": row["fp"], "fn": row["fn"], "tn": row["tn"],
                "precision": f"{row['precision']:.6f}",
                "recall": f"{row['recall']:.6f}",
                "f1": f"{row['f1']:.6f}",
            })


def _round(value: Any) -> Any:
    if isinstance(value, float):
        if np.isnan(value):
            return None
        return round(value, 6)
    return value


def write_metrics_json(path: Path, **payload: Any) -> None:
    """Serialize all metrics deterministically (sorted keys, rounded floats)."""

    def clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: clean(obj[k]) for k in sorted(obj)}
        if isinstance(obj, (list, tuple)):
            return [clean(v) for v in obj]
        if isinstance(obj, OperatingPoint):
            return clean({
                "system": obj.system,
                "max_f1_threshold": obj.max_f1_threshold,
                "high_precision_threshold": obj.high_precision_threshold,
                "high_precision_recall": obj.high_precision_recall,
            })
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return _round(float(obj))
        return _round(obj)

    with path.open("w", encoding="utf-8") as handle:
        json.dump(clean(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
