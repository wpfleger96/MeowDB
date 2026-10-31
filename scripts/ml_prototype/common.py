"""Shared helpers for the offline bark/meow ML prototype.

Heavy ML dependencies (torch, transformers) are imported lazily inside the
functions that need them, so path/resample/hash/heuristic consumers work in an
environment where only the base deps (numpy, scipy, meowdb) are installed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys

from math import gcd
from pathlib import Path
from typing import Any

import numpy as np

from scipy.io import wavfile
from scipy.signal import resample_poly

PROTO_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROTO_DIR.parent.parent

# Allow `import meowdb` when a script is run outside `uv run` (no editable install
# on the path); guarded so we never shadow an already-importable package.
if importlib.util.find_spec("meowdb") is None:
    sys.path.insert(0, str(REPO_ROOT / "src"))

DATA_DIR = PROTO_DIR / "data"
UNITS_DIR = DATA_DIR / "units"
CACHE_DIR = DATA_DIR / "cache"
RESULTS_DIR = DATA_DIR / "results"
LABELS_CSV = DATA_DIR / "labels.csv"
MANIFEST_CSV = RESULTS_DIR / "embeddings_manifest.csv"

AST_CHECKPOINT = "MIT/ast-finetuned-audioset-10-10-0.4593"
AST_SAMPLE_RATE = 16000

LABEL_VALUES = ("bark", "meow", "speech", "noise", "other")
POSITIVE_LABEL = {"dog": "bark", "cat": "meow"}
LABELS_COLUMNS = [
    "unit_id",
    "source_recording",
    "source_kind",
    "start_ms",
    "end_ms",
    "sample_rate",
    "species",
    "label",
    "split_group",
]

# Lazy AST singleton: (feature_extractor, embed_model, zeroshot_model). Loading the
# checkpoint is expensive, so compute once and reuse across all callers.
_AST_BUNDLE: tuple[Any, Any, Any] | None = None


def ensure_dirs() -> None:
    """Create every prototype data directory (idempotent)."""
    for directory in (DATA_DIR, UNITS_DIR, CACHE_DIR, RESULTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def species_results_dir(species: str) -> Path:
    """Per-species results directory, so dog and cat runs never clobber each other."""
    directory = RESULTS_DIR / species
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a WAV as mono float32 in [-1, 1], plus its sample rate.

    Uses scipy.io.wavfile so the prototype has no soundfile read dependency.
    Integer PCM is normalized by its full-scale range; stereo is downmixed by mean.
    """
    sr, data = wavfile.read(path)
    samples = np.asarray(data)
    if samples.dtype == np.int16:
        samples = samples.astype(np.float32) / 32768.0
    elif samples.dtype == np.int32:
        samples = samples.astype(np.float32) / 2147483648.0
    elif samples.dtype == np.uint8:  # WAV 8-bit PCM is unsigned, centered at 128
        samples = (samples.astype(np.float32) - 128.0) / 128.0
    else:
        samples = samples.astype(np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return samples.astype(np.float32), int(sr)


def write_wav_16bit(path: Path, samples: np.ndarray, sr: int) -> None:
    """Write float samples as 16-bit PCM WAV, clipping to [-1, 1] first."""
    clipped = np.clip(samples.astype(np.float32), -1.0, 1.0)
    int_samples = (clipped * 32768.0).astype(np.int16)
    wavfile.write(str(path), int(sr), int_samples)


def resample_to_16k(samples: np.ndarray, sr: int) -> np.ndarray:
    """Resample to 16 kHz (float32). No-op when already at 16 kHz."""
    if sr == AST_SAMPLE_RATE:
        return samples.astype(np.float32)
    divisor = gcd(AST_SAMPLE_RATE, sr)
    up = AST_SAMPLE_RATE // divisor
    down = sr // divisor
    return resample_poly(samples, up, down).astype(np.float32)


def content_hash(samples_16k: np.ndarray) -> str:
    """SHA-256 hex of the 16 kHz float32 samples — a stable per-clip cache key."""
    return hashlib.sha256(samples_16k.astype(np.float32).tobytes()).hexdigest()


def load_ast() -> tuple[Any, Any, Any]:
    """Return the cached (feature_extractor, embed_model, zeroshot_model) triple.

    torch/transformers are imported here, not at module scope, so the module stays
    importable without the opt-in `ml` dependency group. CPU-only, gradients off.
    """
    global _AST_BUNDLE
    if _AST_BUNDLE is None:
        import torch

        from transformers import (
            ASTFeatureExtractor,
            ASTForAudioClassification,
            ASTModel,
        )

        torch.set_grad_enabled(False)
        feature_extractor = ASTFeatureExtractor.from_pretrained(AST_CHECKPOINT)
        embed_model = ASTModel.from_pretrained(AST_CHECKPOINT).eval()
        zeroshot_model = ASTForAudioClassification.from_pretrained(AST_CHECKPOINT).eval()
        _AST_BUNDLE = (feature_extractor, embed_model, zeroshot_model)
    return _AST_BUNDLE


def ast_embedding_and_logits(samples_16k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Embed a 16 kHz clip and score it against AudioSet in one feature extraction.

    Returns (embedding (768,), logits (527,)) as float32. The embedding is the
    mean-pooled AST hidden state; the logits are the raw AudioSet classifier outputs.
    """
    import torch

    feature_extractor, embed_model, zeroshot_model = load_ast()
    inputs = feature_extractor(
        samples_16k, sampling_rate=AST_SAMPLE_RATE, return_tensors="pt"
    )
    with torch.no_grad():
        hidden = embed_model(**inputs).last_hidden_state  # (1, seq, 768)
        embedding = hidden.mean(dim=1).squeeze(0)  # (768,)
        logits = zeroshot_model(**inputs).logits.squeeze(0)  # (527,)
    return (
        embedding.cpu().numpy().astype(np.float32),
        logits.cpu().numpy().astype(np.float32),
    )


def audioset_target_indices() -> dict[str, int]:
    """Map the AudioSet display labels we care about to their class indices.

    Resolves "Bark", "Meow", "Speech", "Dog", "Cat" case-insensitively against the
    classifier's label2id. A missing label raises KeyError with near matches rather
    than silently guessing a wrong index.
    """
    _, _, zeroshot_model = load_ast()
    label2id: dict[str, int] = zeroshot_model.config.label2id
    by_lower = {name.lower(): idx for name, idx in label2id.items()}
    targets = ("Bark", "Meow", "Speech", "Dog", "Cat")
    resolved: dict[str, int] = {}
    for name in targets:
        key = name.lower()
        if key not in by_lower:
            near = [n for n in label2id if key in n.lower() or n.lower() in key]
            raise KeyError(f"AudioSet label {name!r} not found; near matches: {near}")
        resolved[name] = by_lower[key]
    return resolved


def heuristic_verdict(unit_wav: Path, species: str) -> bool:
    """Run the production classifier alone on one clip, returning accept/reject.

    Bypasses the VAD by passing the whole clip as a single candidate segment, so
    this measures the classifier seam in isolation. Unit WAVs are 44100 Hz, so the
    canine highpass-reference bandwidth guard passes.
    """
    from meowdb.processor import SoundProcessor
    from meowdb.species import processor_config_for_species

    proc = SoundProcessor(processor_config_for_species(species))
    _audio, samples, sr = proc._load(unit_wav)
    species_band, reference_band = proc._build_discriminator_signals(samples, sr)
    classified = proc._classify_segments(
        [(0, len(samples))], species_band, reference_band, sr
    )
    return len(classified) > 0


def detect_only_verdict(unit_wav: Path, species: str) -> bool:
    """Run the full detect-only pipeline (VAD + classifier) on one clip."""
    from meowdb.processor import SoundProcessor
    from meowdb.species import processor_config_for_species

    proc = SoundProcessor(processor_config_for_species(species))
    return len(proc.detect_only(unit_wav)) > 0


def zeroshot_probs(logits: np.ndarray) -> np.ndarray:
    """Numerically stable element-wise sigmoid of AudioSet logits.

    AudioSet is multi-label, so each class is an independent sigmoid, not a softmax
    over classes. Splitting on the sign of the logit avoids exp overflow.
    """
    logits = logits.astype(np.float32)
    positive = logits >= 0
    result = np.empty_like(logits)
    result[positive] = 1.0 / (1.0 + np.exp(-logits[positive]))
    exp_neg = np.exp(logits[~positive])
    result[~positive] = exp_neg / (1.0 + exp_neg)
    return result
