# ML prototype: bark/meow classifier comparison

An offline, throwaway prototype that compares three classifiers for detecting a target vocalization (dog bark by default) in the MeowDB audio library: the existing DSP heuristic already shipped in production, a zero-shot Audio Spectrogram Transformer (`MIT/ast-finetuned-audioset-10-10-0.4593`) applied directly to AudioSet logits, and a logistic-regression head trained on frozen 768-dim AST embeddings. It exists to answer whether a small learned head beats the heuristic on your own data before any of it touches production. Nothing here modifies the shipped `meowdb` package — the prototype only imports its detection code so all three classifiers are judged on the identical candidate population — and the heavy ML dependencies are opt-in so the default dev environment stays lean.

## Prerequisites

- `just ml-sync` installs the `ml` dependency group (`torch`, `transformers`, `scikit-learn`, `soundfile`, `matplotlib`). Plain `uv sync` never installs it — the group is opt-in.
- The first `just ml-embed` run downloads the ~350 MB AST checkpoint from HuggingFace into the local HF cache. Network access is needed once; subsequent runs are offline.

## Workflow

1. `just ml-prep dog --raw-recording "path/to/recording.m4a"` slices candidate units out of each recording and mines confirmed positives from the MeowDB library automatically. The `--raw-recording` flag is repeatable; pass `--no-mine-library` to skip library mining and `--permissive` to widen the candidate-unit detector.
2. Hand-label: open `scripts/ml_prototype/data/labels.csv`, listen to the WAVs in `data/units/`, and fill the `label` column for raw-derived rows with one of `bark`, `meow`, `speech`, `noise`, or `other`. Library rows come prefilled. Re-running `ml-prep` preserves your hand labels and only appends newly discovered units.
3. `just ml-embed` computes AST embeddings and zero-shot logits for every unit. Results are cached by audio content hash, so re-runs are instant and only new units are processed.
4. `just ml-train dog` runs leave-one-recording-out cross-validation, a learning curve, and a threshold sweep, then writes results to `scripts/ml_prototype/data/results/`: `report.md`, `metrics.json`, `summary.csv`, `learning_curve.png`, and `threshold_sweep.png`.

## How much data do I need?

Roughly 50 positive vocalization units per species is the feasibility floor; 100–150 is comfortable. Negatives (`speech`, `noise`) come free from the same recordings, so labeling effort concentrates on the positives. Don't guess in the abstract — the learning curve in `report.md` shows accuracy as a function of training-set size, which answers "is my data enough" empirically for your library.

## Notes

- Everything under `data/` is gitignored: it holds personal pet audio, embedding caches, and results. None of it is committed.
