serve:
    uv run meowdb serve

dev:
    uv run meowdb serve --reload

ingest path:
    uv run meowdb ingest "{{path}}"

e2e:
    cd ui && npm run test:e2e

screenshots:
    cd ui && npm run test:screenshots

screenshots-post pr:
    bash scripts/post-screenshots.sh "{{pr}}" ui/screenshots
