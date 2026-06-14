# AGENTS.md

## Quick Commands

```bash
just sync              # Install dependencies (uv sync)
just                   # Type-check + lint + format (no tests)
just test              # Unit + integration tests (excludes e2e)
just test-unit         # Unit tests only
just test-integration  # Integration tests only
just e2e               # Playwright E2E tests (views render correctly, local.just)
just lint              # Auto-fix lint issues
just format            # Auto-fix formatting
just serve             # Start server on :8000 (local.just)
just dev               # Start server with --reload (local.just)
just screenshots       # Capture screenshots for PR review (local.just)
just screenshots-post <pr> # Post screenshots to a PR comment (local.just)
```

## Project Structure

```
src/meowdb/
  config.py              # All paths from MEOWDB_DATA_DIR env var
  db.py                  # MeowDB: sqlite3 CRUD, job staging, stats
  processor.py           # MeowProcessor: frequency-band segmentation pipeline
  models.py              # Dataclasses (MeowSegment, ProcessingResult, ProcessorConfig)
  api/
    app.py               # FastAPI factory, lifespan, static mount, SPA catch-all
    streaming.py          # Shared range-header streaming + safe_path containment
    models.py             # Pydantic request/response schemas
    routers/{meows,ingest,audio,stats}.py
  cli/
    commands/{ingest,serve,play,list,delete,stats}.py
  static/                # Vanilla JS + Alpine.js SPA (no build step)
    js/app.js             # Client-side router, Alpine.data() registrations
tests/
  unit/test_db.py         # 48 tests — MeowDB CRUD, job staging
  unit/test_processor.py  # Synthetic audio segmentation tests
  integration/test_api.py # FastAPI TestClient endpoint tests
  integration/test_cli.py # Click CliRunner tests
  e2e/test_ingest.py      # Real .m4a file processing (local only)
ui/                       # Playwright E2E & screenshot tests (Node/TypeScript)
```

## Key Patterns

**Alpine.js script load order** -- Alpine auto-starts on load, so it MUST be the last deferred script:
```html
<!-- ✅ App scripts first, Alpine last -->
<script src="/static/js/app.js" defer></script>
<script src="/static/vendor/alpine.min.js" defer></script>

<!-- ❌ Alpine first — components undefined when Alpine starts -->
<script src="/static/vendor/alpine.min.js" defer></script>
<script src="/static/js/app.js" defer></script>
```

**DB method ownership** -- file moves, path resolution, and SQL all live in `MeowDB`. Routers/CLI call `db.commit_job(job_id, accepted, rejected, wav_dir, mp3_dir)` -- never `db._conn` directly.

**Config patching in tests** -- every router module that imports a config constant needs its own patch target:
```python
# ✅ Patch at every import site
patch("meowdb.api.routers.audio.MP3_DIR", tmp_mp3)
patch("meowdb.api.routers.meows.WAV_DIR", tmp_wav)

# ❌ Only patching app.py — routers still use production paths
patch("meowdb.api.app.MP3_DIR", tmp_mp3)
```

**Shared CLI options** -- use `@db_path_option` from `cli/options.py`, never inline `@click.option("--db-path", ...)`.

## Testing

- `just test` runs unit + integration (99 tests, 75% coverage)
- Processor tests skip without ffmpeg: `@pytest.mark.skipif(shutil.which("ffmpeg") is None)`
- E2e tests skip without local audio files
- Integration tests need `_make_silent_wav_bytes()` for real file fixtures
- `commit_job` tests must create real WAV+MP3 staging files (shutil.move happens inside)
- E2E tests: `just test-e2e` runs Playwright specs verifying views render (desktop only, no screenshots)
- Screenshots: `just screenshots` captures desktop + mobile PNGs locally (requires `npm ci` in `ui/` first)

## Common Gotchas

1. **numpy clip before multiply** -- `np.clip(arr, -1, 1)` THEN `* 32768` THEN cast int16. Reversed order causes silent overflow
2. **FastAPI route order** -- `/meows/random` must register BEFORE `/{id}` or "random" matches as path param
3. **CORS port** -- `app.py` allows `:8000` only. Screenshot tests use `:8001` (same-origin, CORS irrelevant)
4. **`x-if` vs `x-show`** -- play view uses `<template x-if="meowCount > 0">` which removes DOM elements entirely until condition is true. Don't wait for elements inside `x-if` until the async data has loaded
5. **Upload size** -- capped at 500MB with chunked streaming. `await file.read()` is prohibited

## Key Files by Task

| Task | Files |
|------|-------|
| Add API endpoint | `api/routers/*.py`, `api/models.py`, `tests/integration/test_api.py` |
| Add CLI command | `cli/commands/*.py`, `cli/__init__.py` (_register_commands), `tests/integration/test_cli.py` |
| Change DB schema | `db.py` (CREATE TABLE in __init__), `tests/unit/test_db.py` |
| Modify audio pipeline | `processor.py`, `models.py`, `tests/unit/test_processor.py` |
| Frontend changes | `static/js/views/*.js`, `static/index.html`, `static/css/views.css` |
| Add E2E view test | `ui/views.spec.ts`, `ui/seed.py` (if new data needed) |
| Config/paths | `config.py` (single source), patch all import sites in tests |
