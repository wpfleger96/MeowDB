# ML prototype: bark/meow classifier comparison

An offline, throwaway prototype that compares three classifiers for detecting a target vocalization (dog bark by default) in the MeowDB audio library: the existing DSP heuristic already shipped in production, a zero-shot Audio Spectrogram Transformer (`MIT/ast-finetuned-audioset-10-10-0.4593`) applied directly to AudioSet logits, and a logistic-regression head trained on frozen 768-dim AST embeddings. It exists to answer whether a small learned head beats the heuristic on your own data before any of it touches production. Nothing here modifies the shipped `meowdb` package — the prototype only imports its detection code so all three classifiers are judged on the identical candidate population — and the heavy ML dependencies are opt-in so the default dev environment stays lean.

## Prerequisites

- `just ml-sync` installs the `ml` dependency group (`torch`, `transformers`, `scikit-learn`, `soundfile`, `matplotlib`). Plain `uv sync` never installs it — the group is opt-in.
- The first `just ml-embed` run downloads the ~350 MB AST checkpoint from HuggingFace into the local HF cache. Network access is needed once; subsequent runs are offline.

## Workflow

Both species share one `labels.csv` and one embedding cache; only the prep and train steps are per-species. A full dual-species pass looks like:

1. `just ml-prep dog --raw-recording "path/to/dog-recording.m4a"` slices candidate units out of each recording with the dog detector and mines confirmed dog positives from the MeowDB library automatically. The `--raw-recording` flag is repeatable; pass `--no-mine-library` to skip library mining and `--permissive` to widen the candidate-unit detector.
2. `just ml-prep cat --raw-recording "path/to/cat-recording.m4a"` does the same for cats. Rows from both runs coexist in `labels.csv` (each row carries a `species` column, and raw unit IDs are species-prefixed).
3. Hand-label: open `scripts/ml_prototype/data/labels.csv`, listen to the WAVs in `data/units/`, and fill the `label` column for raw-derived rows with one of `bark`, `meow`, `speech`, `noise`, or `other`. Library rows come prefilled. Re-running `ml-prep` preserves your hand labels and only appends newly discovered units.
4. `just ml-embed` computes AST embeddings and zero-shot logits for every labeled unit of every species in one pass. Results are cached by audio content hash, so re-runs are instant and only new units are processed.
5. `just ml-train dog` and `just ml-train cat` each run leave-one-recording-out cross-validation, a learning curve, and a threshold sweep on that species' units only, writing to `scripts/ml_prototype/data/results/<species>/`: `report.md`, `metrics.json`, `summary.csv`, `learning_curve.png`, and `threshold_sweep.png`. The two result sets never overwrite each other.

Each species trains its own binary head (`bark` vs. rest, `meow` vs. rest) rather than one combined multi-class model: production ingest always knows the animal's species at upload time, so the classifier never has to guess between cat and dog.

## How much data do I need?

Roughly 50 positive vocalization units per species is the feasibility floor; 100–150 is comfortable. Negatives (`speech`, `noise`) come free from the same recordings, so labeling effort concentrates on the positives. Don't guess in the abstract — the learning curve in `report.md` shows accuracy as a function of training-set size, which answers "is my data enough" empirically for your library.

## Notes

- Everything under `data/` is gitignored: it holds personal pet audio, embedding caches, and results. None of it is committed.
