# Project-specific recipes that survive Justfile template syncs.

# Start dev server (no auth required on localhost)
serve:
    uv run meowdb serve

# Start dev server with hot-reload (no auth required on localhost)
dev:
    uv run meowdb serve --reload

# Start dev server with password auth enabled (password: test)
dev-auth:
    #!/usr/bin/env bash
    set -euo pipefail
    HASH=$(uv run python -c "import bcrypt; print(bcrypt.hashpw(b'test', bcrypt.gensalt()).decode())")
    MEOWDB_PASSWORD_HASH="$HASH" MEOWDB_SESSION_SECRET="dev-secret" uv run meowdb serve

# Ingest an audio file into the local library
ingest path:
    uv run meowdb ingest "{{path}}"

# Run Playwright end-to-end tests
e2e:
    cd ui && npm run test:e2e

# Run auth-gated Playwright e2e tests
e2e-auth:
    cd ui && npm run test:e2e:auth

# Capture UI screenshots with Playwright
screenshots:
    cd ui && npm run test:screenshots

# Post screenshots from a PR run to GitHub
screenshots-post pr:
    bash scripts/post-screenshots.sh "{{pr}}" ui/screenshots

# Sync the opt-in ML prototype dependency group
ml-sync:
    uv sync --group ml

# Extract candidate units + mine library positives (hand-edit scripts/ml_prototype/data/labels.csv after)
[positional-arguments]
ml-prep species="dog" *args:
    #!/usr/bin/env bash
    exec uv run --group ml python scripts/ml_prototype/prepare_data.py --species "$1" "${@:2}"

# Rapid keyboard labeling UI with model suggestions (writes labels.csv as you go)
[positional-arguments]
ml-label *args:
    #!/usr/bin/env bash
    exec uv run --group ml python scripts/ml_prototype/label_units.py "$@"

# Compute AST embeddings + zero-shot logits (content-addressed cache)
[positional-arguments]
ml-embed *args:
    #!/usr/bin/env bash
    exec uv run --group ml python scripts/ml_prototype/extract_embeddings.py "$@"

# Train head, run LORO CV + learning curve + threshold sweep, write report
[positional-arguments]
ml-train species="dog" *args:
    #!/usr/bin/env bash
    exec uv run --group ml python scripts/ml_prototype/train_eval.py --species "$1" "${@:2}"
