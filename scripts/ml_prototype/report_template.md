# Bark/meow classifier comparison — {species} ({positive_label})

Offline prototype comparing three classifiers for the target vocalization on one
labeled unit population. Positive class: `{positive_label}`. Seed: `{seed}`.

## Dataset

- Labeled units: **{n_units}** ({n_positive} positive, {n_negative} negative)
- Recordings (leave-one-recording-out groups): **{n_groups}**
- Units scored by the learned head (out-of-fold): **{n_eval_units}** ({n_unpredicted} dropped from degenerate folds)
- Provenance: **{n_library}** library-mined, **{n_raw}** raw-derived

Label counts:

{label_counts_table}

Source-kind counts:

{source_kind_table}

## Method

- Checkpoint: `{checkpoint}` (CPU, gradients off).
- Features: mean-pooled 768-dim AST hidden state per clip; zero-shot decisions read the 527-dim AudioSet logits from the same forward pass.
- Learned head: `StandardScaler` -> `LogisticRegression(class_weight="balanced")` on the frozen embeddings. Class weighting offsets the positive/negative imbalance without resampling.
- Validation: {cv_scheme}. Out-of-fold predictions are accumulated per unit so every learned-head number is on held-out data.
- Requested heads: `{head_flag}`.

The three systems are judged on the **identical** unit set (the units the learned head could score), so differences reflect the classifier, not the sample.

## Results

All metrics are binary (positive = `{positive_label}`) on the shared evaluation set.

{results_table}

## Learning curve

How many positive examples the learned head needs, measured by retraining on
subsampled positives within each fold's training split and scoring the held-out
fold. Bands are +/-1 standard deviation across folds.

{learning_curve_image}

{learning_curve_table}

{learning_curve_verdict}

## Threshold sweep

Precision-recall curves for the learned head (out-of-fold) and the zero-shot
target-class probability, with the heuristic (classifier-only) as a single
operating point. Two operating points are selected per swept system: the
maximum-F1 threshold and the highest-recall threshold holding precision >= 0.95.

{threshold_sweep_image}

Chosen operating points:

{operating_points_table}

## Failure analysis

False accepts (predicted positive, labeled otherwise) and false rejects
(labeled positive, predicted negative) per system, capped at 20 each. Labels are
shown to expose which negatives are confusable.

{failure_analysis}

## Production implications

The DSP heuristic ships today at zero added dependencies and no model
distribution: it is already in the production `meowdb` package. Adopting the
learned head would require exporting the small logistic-regression head (plus the
`StandardScaler`) to ONNX and distributing the weights at Docker build time,
alongside an ONNX-exported embedding extractor. `torch` and `transformers` stay
out of the production image regardless — the head runs on precomputed embeddings,
and only the offline prototype loads the full checkpoint. The learned head is
worth shipping only if the table above shows it clearing the heuristic by a margin
that justifies that build-time and maintenance cost.
