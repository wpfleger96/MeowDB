# MeowDB

[![CI](https://github.com/wpfleger96/meowdb/actions/workflows/ci.yml/badge.svg)](https://github.com/wpfleger96/meowdb/actions/workflows/ci.yml)

A personal cat meow library. Record, upload, and play back cat meow audio clips. Live at [meowdb.app](https://meowdb.app).

## Architecture

```
Browser → Cloudflare (CDN/WAF/geo-block/rate-limit) → Fly.io (Anycast) → MeowDB (FastAPI + SQLite)
```

- **Compute:** Fly.io `shared-cpu-1x` / 512MB, Seattle (sjc) region, auto-stop/auto-start
- **Storage:** Fly.io NVMe volume (`meowdb_data`, 1GB) mounted at `/data` for SQLite + audio files
- **CDN/Security:** Cloudflare proxy — DDoS protection, geo-blocking (US only), login rate limiting, bot protection
- **Auth:** Shared password via bcrypt + Starlette `SessionMiddleware` (14-day HttpOnly cookies)
- **Infrastructure as code:** Cloudflare DNS, WAF, and zone settings managed in [homelabconfigs](https://github.com/wpfleger96/homelabconfigs)

## Local Development

```bash
# Install dependencies
uv sync

# Start dev server (no auth required at localhost)
meowdb serve

# Start dev server with auth enabled (password: test)
just dev-auth

# Run checks (type, lint, format)
just check

# Run tests
just test
```

Run `just --list` for all available recipes.

## Docker

```bash
# Start with persistent volume
docker compose up

# Rebuild after code changes
docker compose up --build
```

The compose setup mounts a named volume at `/data` for SQLite and audio files.

## Deployment

Deploys automatically on push to `main` via `.github/workflows/fly-deploy.yml` using `flyctl deploy --remote-only`. The image is built remotely by Fly.io's Depot builder.

To deploy manually:

```bash
fly deploy
```

## Fly.io First-Time Setup

These are one-time commands run during initial provisioning:

```bash
# Authenticate
fly auth login

# Create the app (fly.toml already exists)
fly launch --name meowdb --region sjc --ha=false --no-deploy

# Create persistent volume
fly volumes create meowdb_data --size 1 --region sjc

# Generate and set secrets
fly secrets set MEOWDB_CORS_ORIGINS=https://meowdb.app
fly secrets set MEOWDB_PASSWORD_HASH="$(python -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt()).decode())")"
fly secrets set MEOWDB_SESSION_SECRET="$(python -c "import secrets; print(secrets.token_urlsafe(48))")"

# Deploy
fly deploy

# Add custom domain (run after DNS records are in Cloudflare)
fly certs add meowdb.app
```

The `FLY_API_TOKEN` GitHub secret is set automatically by `fly launch`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEOWDB_DATA_DIR` | `~/.local/share/meowdb` | Directory for SQLite DB and audio files |
| `MEOWDB_HOST` | `127.0.0.1` | Bind address (set to `0.0.0.0` in production) |
| `MEOWDB_PORT` | `8000` | Listen port |
| `MEOWDB_CORS_ORIGINS` | `http://localhost:8000,...` | Comma-separated allowed CORS origins |
| `MEOWDB_PASSWORD_HASH` | _(empty — auth disabled)_ | bcrypt hash of shared password |
| `MEOWDB_SESSION_SECRET` | _(dev placeholder)_ | Signing key for session cookies |

## Infrastructure

Cloudflare configuration (DNS, WAF, zone settings) is managed via Terraform in [homelabconfigs](https://github.com/wpfleger96/homelabconfigs/tree/main/terraform/cloudflare). Changes there deploy automatically on merge to main.
