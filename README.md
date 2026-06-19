# MeowDB

[![GitHub Contributors](https://img.shields.io/github/contributors/wpfleger96/MeowDB.svg)](https://github.com/wpfleger96/MeowDB/graphs/contributors)
[![CI](https://github.com/wpfleger96/meowdb/actions/workflows/ci.yml/badge.svg)](https://github.com/wpfleger96/meowdb/actions/workflows/ci.yml)
[![Lines of Code](https://aschey.tech/tokei/github/wpfleger96/MeowDB?category=code)](https://github.com/wpfleger96/MeowDB)
[![License](https://img.shields.io/github/license/wpfleger96/MeowDB.svg)](https://github.com/wpfleger96/MeowDB/blob/main/LICENSE)

A personal cat meow library. Record, upload, and play back cat meow audio clips. Live at [meowdb.app](https://meowdb.app).

## Architecture

```
Browser → Cloudflare (CDN/WAF/geo-block/rate-limit) → Cloudflare Tunnel → Proxmox LXC → MeowDB (FastAPI + SQLite)
```

- **Compute:** Proxmox LXC container (Debian 12, Docker) on homelab, 1GB RAM
- **Storage:** Bind-mounted `/data` directory on LXC container for SQLite + audio files
- **CDN/Security:** Cloudflare proxy — DDoS protection, geo-blocking (US only), login rate limiting, bot protection
- **Ingress:** Cloudflare Tunnel (`cloudflared`) — zero firewall changes, no public IP exposure
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

Deploys automatically on push to `main` via `.github/workflows/deploy.yml`. The workflow builds the Docker image and pushes it to `ghcr.io/wpfleger96/meowdb:latest`. [Watchtower](https://containrrr.dev/watchtower/) on the server polls GHCR every 5 minutes and auto-restarts the container on new images.

## Production Setup

The production stack runs via `docker-compose.prod.yml` with three services:

- `meowdb` — the app (pulled from GHCR)
- `cloudflared` — Cloudflare Tunnel daemon
- `watchtower` — auto-pulls new images from GHCR

Secrets are stored in `.env` on the server (not committed):

| Variable | Description |
|----------|-------------|
| `MEOWDB_PASSWORD_HASH` | bcrypt hash of shared password |
| `MEOWDB_SESSION_SECRET` | Signing key for session cookies |
| `MEOWDB_CORS_ORIGINS` | `https://meowdb.app` |
| `TUNNEL_TOKEN` | Cloudflare Tunnel authentication token |

Generate secrets:

```bash
# Password hash
python -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt()).decode())"

# Session secret
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Infrastructure (LXC container, Cloudflare Tunnel, DNS) is managed in [homelabconfigs](https://github.com/wpfleger96/homelabconfigs).

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

Cloudflare configuration (DNS, WAF, Cloudflare Tunnel, zone settings) and the Proxmox LXC container are managed via Terraform in [homelabconfigs](https://github.com/wpfleger96/homelabconfigs). Cloudflare changes deploy automatically on merge to main; homelab changes are applied locally.
