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

# Capture UI screenshots with Playwright
screenshots:
    cd ui && npm run test:screenshots

# Post screenshots from a PR run to GitHub
screenshots-post pr:
    bash scripts/post-screenshots.sh "{{pr}}" ui/screenshots
