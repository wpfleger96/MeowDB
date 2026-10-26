"""Model-assisted rapid labeling UI for the offline bark/meow ML prototype.

Serves a self-contained, keyboard-driven local web page that plays each unlabeled
audio unit, preselects the pretrained AST model's guessed label, and writes the
operator's decision straight into `labels.csv` on every keystroke (atomically, so
a crash loses nothing). One keypress per clip: `b`/`m`/`s`/`n`/`o` assign a label,
Enter accepts the model suggestion, Space replays, `u` undoes.

Stdlib-only server (`http.server`). The heavy model (torch/transformers) is loaded
lazily inside `common.ast_embedding_and_logits`, and only for units that miss the
embedding cache — the same content-addressed cache `extract_embeddings.py` fills,
so pre-computing suggestions here also pre-pays `just ml-embed`. Pass
`--no-suggest` to skip the model entirely (no torch needed).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import webbrowser

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np

# The prototype dir is not a package; put it on the path so `import common` works
# no matter the cwd (script run, `-m`, or imported by a throwaway test harness).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CACHE_DIR,
    LABEL_VALUES,
    LABELS_COLUMNS,
    LABELS_CSV,
    UNITS_DIR,
    ast_embedding_and_logits,
    content_hash,
    read_wav,
    resample_to_16k,
    zeroshot_probs,
)

# unit ids use letters/digits/underscores/dots/hyphens; anything else (notably a
# path separator) is rejected before a request path ever reaches the filesystem.
UNIT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Below this suggestion score, the model isn't confident about bark/meow/speech,
# so we fall back to "noise" rather than assert a weak positive.
SUGGEST_FLOOR = 0.10

# Verified AudioSet-527 class indices for the MIT/ast checkpoint.
IDX_BARK, IDX_DOG = 75, 74
IDX_MEOW, IDX_CAT = 83, 81
IDX_SPEECH = 0

DOWNLOAD_NOTE = (
    "  (first model load downloads the ~350 MB AST checkpoint via transformers)"
)


def suggestion_for(logits: np.ndarray) -> tuple[str, dict[str, float]]:
    """Map AudioSet logits to a suggested label plus the three display scores.

    bark = max(Bark, Dog), meow = max(Meow, Cat), speech = Speech; the suggestion
    is the argmax of those three, or "noise" when even the winner is below the
    confidence floor.
    """
    probs = zeroshot_probs(logits)
    scores = {
        "bark": float(max(probs[IDX_BARK], probs[IDX_DOG])),
        "meow": float(max(probs[IDX_MEOW], probs[IDX_CAT])),
        "speech": float(probs[IDX_SPEECH]),
    }
    best = max(scores, key=scores.get)
    label = best if scores[best] >= SUGGEST_FLOOR else "noise"
    return label, scores


def load_rows(labels_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read the labels CSV into row dicts, returning (rows, fieldnames).

    Fails loudly if the CSV is absent — that means prepare_data has not run yet.
    The file's own header is preserved for round-tripping; LABELS_COLUMNS is the
    fallback only for a headerless file.
    """
    if not labels_path.exists():
        raise SystemExit(
            f"labels CSV not found: {labels_path}\n"
            "Run prepare_data.py first to slice units and create the labels file."
        )
    with labels_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames or LABELS_COLUMNS)
    return rows, fieldnames


def save_rows_atomic(
    labels_path: Path, fieldnames: list[str], rows: list[dict[str, str]]
) -> None:
    """Persist rows to labels.csv atomically: full write to a temp file in the
    same directory, then os.replace onto the real path. Every keystroke is durable
    and an interrupted write can never leave a truncated CSV."""
    fd, tmp_name = tempfile.mkstemp(
        dir=str(labels_path.parent), prefix=".labels-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        os.replace(tmp_name, labels_path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def compute_suggestions(
    queue_rows: list[dict[str, str]], units_dir: Path, cache_dir: Path
) -> dict[str, dict]:
    """Pre-compute a model suggestion per queued unit, filling the embedding cache.

    Reuses (and populates) the same `<content_hash>.npz` cache as
    extract_embeddings.py, so a unit computed here is a cache hit for `ml-embed`.
    The model is only touched on a cache miss.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    suggestions: dict[str, dict] = {}
    total = len(queue_rows)
    computed = 0
    for index, row in enumerate(queue_rows, start=1):
        unit_id = row["unit_id"]
        wav_path = units_dir / f"{unit_id}.wav"
        if not wav_path.exists():
            print(f"  [{index}/{total}] {unit_id}: WAV missing — no suggestion")
            continue

        samples_16k = resample_to_16k(*read_wav(wav_path))
        cache_path = cache_dir / f"{content_hash(samples_16k)}.npz"

        logits = None
        if cache_path.exists():
            with np.load(cache_path) as data:
                if "zeroshot_logits" in data:
                    logits = data["zeroshot_logits"]
        if logits is None:
            if computed == 0:  # first compute of the run — warn about the download
                print(DOWNLOAD_NOTE)
            embedding, logits = ast_embedding_and_logits(samples_16k)
            np.savez(cache_path, embedding=embedding, zeroshot_logits=logits)
            computed += 1
            print(f"  [{index}/{total}] {unit_id}: computed")
        else:
            print(f"  [{index}/{total}] {unit_id}: cache hit")

        label, scores = suggestion_for(logits)
        suggestions[unit_id] = {"suggestion": label, "scores": scores}
    return suggestions


class LabelState:
    """In-memory model of labels.csv shared by every request handler."""

    def __init__(
        self,
        labels_path: Path,
        units_dir: Path,
        rows: list[dict[str, str]],
        fieldnames: list[str],
        suggestions: dict[str, dict],
    ) -> None:
        self.labels_path = labels_path
        self.units_dir = units_dir.resolve()
        self.rows = rows
        self.fieldnames = fieldnames
        self.suggestions = suggestions
        self._by_id = {row["unit_id"]: row for row in rows}

    def queue(self) -> list[dict]:
        """The still-unlabeled units, sorted by unit_id, each with its suggestion."""
        items = []
        for row in self.rows:
            if (row.get("label") or "").strip():
                continue
            sug = self.suggestions.get(
                row["unit_id"], {"suggestion": None, "scores": None}
            )
            items.append(
                {
                    "unit_id": row["unit_id"],
                    "source_recording": row.get("source_recording", ""),
                    "species": row.get("species", ""),
                    "suggestion": sug["suggestion"],
                    "scores": sug["scores"],
                }
            )
        items.sort(key=lambda item: item["unit_id"])
        return items

    def totals(self) -> dict[str, int]:
        total = len(self.rows)
        remaining = sum(1 for r in self.rows if not (r.get("label") or "").strip())
        return {"total": total, "labeled": total - remaining, "remaining": remaining}

    def set_label(self, unit_id: str, label: str) -> bool:
        """Update one row's label (label "" un-labels) and persist. False if no row."""
        row = self._by_id.get(unit_id)
        if row is None:
            return False
        row["label"] = label
        save_rows_atomic(self.labels_path, self.fieldnames, self.rows)
        return True

    def audio_path(self, unit_id: str) -> Path | None:
        """Resolve a unit_id to its WAV, or None if invalid/outside the units dir."""
        if not UNIT_ID_RE.match(unit_id):
            return None
        candidate = (self.units_dir / f"{unit_id}.wav").resolve()
        if candidate.parent != self.units_dir or not candidate.is_file():
            return None
        return candidate


class Handler(BaseHTTPRequestHandler):
    server_version = "MeowDBLabeler/1.0"

    def log_message(self, *args: object) -> None:  # keep the console clean
        pass

    @property
    def state(self) -> LabelState:
        return self.server.state  # type: ignore[attr-defined]

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/state":
            self._send_json({"queue": self.state.queue(), "totals": self.state.totals()})
        elif path.startswith("/audio/"):
            self._serve_audio(unquote(path[len("/audio/") :]))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/label":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, status=400)
            return
        unit_id = data.get("unit_id", "")
        label = data.get("label", "")
        if label != "" and label not in LABEL_VALUES:
            self._send_json({"error": f"invalid label {label!r}"}, status=400)
            return
        if not self.state.set_label(unit_id, label):
            self._send_json({"error": f"unknown unit_id {unit_id!r}"}, status=404)
            return
        self._send_json({"ok": True, "totals": self.state.totals()})

    def _serve_audio(self, unit_id: str) -> None:
        wav_path = self.state.audio_path(unit_id)
        if wav_path is None:
            self.send_error(404)
            return
        body = wav_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MeowDB rapid labeling</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto;
         padding: 0 1rem; line-height: 1.5; }
  h1 { font-size: 1.1rem; margin: 0 0 0.25rem; }
  .progress { color: #888; font-size: 0.85rem; margin-bottom: 1rem; }
  .meta { margin: 0.5rem 0; }
  .meta code { background: rgba(128,128,128,0.15); padding: 0.1rem 0.35rem;
               border-radius: 4px; }
  audio { width: 100%; margin: 0.75rem 0; }
  .labels { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.75rem 0; }
  .chip { border: 1px solid rgba(128,128,128,0.4); border-radius: 6px;
          padding: 0.4rem 0.7rem; font-size: 0.95rem; }
  .chip .key { font-weight: 700; text-transform: uppercase; }
  .chip.suggested { border-color: #2a7; box-shadow: 0 0 0 2px rgba(34,170,119,0.4);
                    font-weight: 600; }
  .scores { color: #888; font-size: 0.8rem; margin: 0.5rem 0; }
  .help { color: #999; font-size: 0.8rem; margin-top: 1.5rem; }
  .done { font-size: 1.05rem; margin-top: 2rem; }
  .done code { background: rgba(128,128,128,0.15); padding: 0.1rem 0.35rem;
               border-radius: 4px; }
</style>
</head>
<body>
<div id="app">Loading…</div>
<script>
const LABEL_KEYS = { b: "bark", m: "meow", s: "speech", n: "noise", o: "other" };
let queue = [];
let index = 0;
let labeledThisSession = 0;

async function post(unit_id, label) {
  await fetch("/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ unit_id, label }),
  });
}

async function assign(label) {
  if (index >= queue.length) return;
  const item = queue[index];
  await post(item.unit_id, label);
  if (!item.label) labeledThisSession += 1;
  item.label = label;
  index += 1;
  render();
}

function acceptSuggestion() {
  if (index >= queue.length) return;
  const item = queue[index];
  if (item.suggestion) assign(item.suggestion);
}

async function undo() {
  if (index === 0) return;
  index -= 1;
  const item = queue[index];
  await post(item.unit_id, "");
  if (item.label) labeledThisSession = Math.max(0, labeledThisSession - 1);
  item.label = "";
  render();
}

function replay() {
  const audio = document.querySelector("audio");
  if (audio) { audio.currentTime = 0; audio.play().catch(() => {}); }
}

function fmt(scores) {
  if (!scores) return "no model suggestion (--no-suggest)";
  return ["bark", "meow", "speech"]
    .map((k) => `${k} ${scores[k].toFixed(2)}`)
    .join("   ");
}

function render() {
  const app = document.getElementById("app");
  if (index >= queue.length) {
    app.innerHTML =
      `<div class="done">All done — ${labeledThisSession} labeled this session. ` +
      `Run <code>just ml-embed</code> next.</div>`;
    return;
  }
  const item = queue[index];
  const chips = Object.entries(LABEL_KEYS)
    .map(([key, label]) => {
      const suggested = label === item.suggestion ? " suggested" : "";
      return `<span class="chip${suggested}"><span class="key">${key}</span> ${label}</span>`;
    })
    .join("");
  app.innerHTML = `
    <h1>MeowDB rapid labeling</h1>
    <div class="progress">${index + 1} of ${queue.length} remaining</div>
    <div class="meta"><code>${item.unit_id}</code></div>
    <div class="meta">recording: ${item.source_recording || "—"} &nbsp;·&nbsp; species: ${item.species || "—"}</div>
    <audio src="/audio/${encodeURIComponent(item.unit_id)}" controls autoplay></audio>
    <div class="labels">${chips}</div>
    <div class="scores">${fmt(item.scores)}</div>
    <div class="help">
      keys: <b>b</b> bark · <b>m</b> meow · <b>s</b> speech · <b>n</b> noise ·
      <b>o</b> other · <b>Enter</b> accept suggestion · <b>Space</b> replay ·
      <b>u</b> undo
    </div>`;
}

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const key = event.key.toLowerCase();
  if (key in LABEL_KEYS) { event.preventDefault(); assign(LABEL_KEYS[key]); }
  else if (event.key === "Enter") { event.preventDefault(); acceptSuggestion(); }
  else if (event.key === " ") { event.preventDefault(); replay(); }
  else if (key === "u") { event.preventDefault(); undo(); }
});

fetch("/state")
  .then((response) => response.json())
  .then((data) => { queue = data.queue; render(); });
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Keyboard-driven, model-assisted labeling UI for prototype units."
    )
    parser.add_argument("--labels", type=Path, default=LABELS_CSV,
                        help=f"labels CSV to read/write (default: {LABELS_CSV})")
    parser.add_argument("--units-dir", type=Path, default=UNITS_DIR,
                        help=f"directory of unit WAVs (default: {UNITS_DIR})")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR,
                        help=f"embedding cache directory (default: {CACHE_DIR})")
    parser.add_argument("--port", type=int, default=8017, help="listen port (default: 8017)")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open a web browser automatically")
    parser.add_argument("--no-suggest", action="store_true",
                        help="skip model suggestions entirely (no torch needed)")
    args = parser.parse_args(argv)

    rows, fieldnames = load_rows(args.labels)
    queue_rows = sorted(
        (r for r in rows if not (r.get("label") or "").strip()),
        key=lambda r: r["unit_id"],
    )
    totals = {"total": len(rows), "remaining": len(queue_rows)}
    print(
        f"{totals['total']} units total — "
        f"{totals['total'] - totals['remaining']} labeled, "
        f"{totals['remaining']} remaining"
    )

    suggestions: dict[str, dict] = {}
    if not args.no_suggest and queue_rows:
        suggestions = compute_suggestions(queue_rows, args.units_dir, args.cache_dir)

    state = LabelState(args.labels, args.units_dir, rows, fieldnames, suggestions)
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    server.state = state  # type: ignore[attr-defined]

    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        webbrowser.open(url)
    print(f"Serving {url}")
    print("Ctrl-C when done (labels are saved as you go)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
