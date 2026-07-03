from __future__ import annotations

import json
import logging
import re

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from html import escape as html_escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from meowdb import __version__
from meowdb.api import auth
from meowdb.api.routers import audio, ingest, meows, photos, stats, uniqueness
from meowdb.config import (
    _DEFAULT_SESSION_SECRET,
    CORS_ORIGINS,
    DATA_DIR,
    DB_PATH,
    IS_LOCALHOST,
    MP3_DIR,
    PHOTOS_DIR,
    SESSION_SECRET,
    STAGING_DIR,
    UPLOAD_ACCEPT,
    WAV_DIR,
)

_STATIC_DIR = Path(__file__).parent.parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"
_logger = logging.getLogger(__name__)
_HASHED_ASSET_RE = re.compile(r"\.[0-9a-f]{8}\.(js|css)$")


def _migrate_photos(db: Any, logger: logging.Logger) -> None:
    from meowdb.photos import optimize_photo

    photos = db.get_photos()
    migrated = 0
    for photo in photos:
        if photo["filename"].endswith(".webp"):
            continue
        orig_path = PHOTOS_DIR / photo["filename"]
        if not orig_path.exists():
            logger.warning("Migration: photo file missing, skipping: %s", orig_path)
            continue
        optimized_path = optimize_photo(orig_path)
        db.update_photo_filename(photo["id"], optimized_path.name)
        orig_path.unlink(missing_ok=True)
        logger.info("Migration: converted %s → %s", orig_path.name, optimized_path.name)
        migrated += 1
    if migrated == 0:
        logger.info("Migration: no photos needed conversion")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    from meowdb.db import MeowDB

    if CORS_ORIGINS == ["*"]:
        _logger.warning("MEOWDB_CORS_ORIGINS='*' — all origins are allowed")
    elif not CORS_ORIGINS:
        _logger.warning(
            "MEOWDB_CORS_ORIGINS resolved to empty list — all cross-origin requests will be blocked"
        )

    if SESSION_SECRET == _DEFAULT_SESSION_SECRET and not IS_LOCALHOST:
        _logger.warning(
            "MEOWDB_SESSION_SECRET is using the default value — session cookies are forgeable"
        )

    for directory in (DATA_DIR, WAV_DIR, MP3_DIR, STAGING_DIR, PHOTOS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    app.state.db = MeowDB(DB_PATH)
    _migrate_photos(app.state.db, _logger)
    yield
    app.state.db.close()


class _NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        response: Response = await call_next(request)
        if request.url.path.startswith("/static/"):
            if _HASHED_ASSET_RE.search(request.url.path):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif request.url.path == "/static/sw.js":
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            else:
                response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="MeowDB", lifespan=_lifespan)

    app.add_middleware(_NoCacheStaticMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET,
        max_age=7 * 24 * 3600,
        https_only=not IS_LOCALHOST,
        same_site="lax",
    )

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(auth.router, prefix="/api")
    app.include_router(meows.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(audio.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(photos.router, prefix="/api")
    app.include_router(uniqueness.router, prefix="/api")

    @app.get("/health", include_in_schema=False, response_model=None)
    async def health(request: Request) -> JSONResponse:
        if not request.app.state.db.ping():
            return JSONResponse({"status": "error"}, status_code=503)
        return JSONResponse({"status": "ok"})

    @app.get("/api/version", include_in_schema=False, response_model=None)
    async def version_info() -> JSONResponse:
        return JSONResponse({"version": __version__})

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_catch_all(full_path: str, request: Request) -> HTMLResponse:
        html = _INDEX_HTML.read_text(encoding="utf-8").replace("{{UPLOAD_ACCEPT}}", UPLOAD_ACCEPT)
        bootstrap_json, preload = "null", ""
        try:
            db = request.app.state.db
            photo = db.get_random_photo()
            photo_payload = photos.photo_to_response(photo).model_dump() if photo else None
            payload = {
                "meow_count": db.get_count(),
                "auth": auth.auth_status_payload(request),
                "photo": photo_payload,
            }
            bootstrap_json = json.dumps(payload).replace("<", "\\u003c")
            if full_path == "" and photo_payload:  # full_path is "" for the root "/" request
                href = html_escape(photo_payload["image_url"], quote=True)
                preload = f'<link rel="preload" as="image" href="{href}">'
        except Exception:
            _logger.exception("bootstrap payload failed; serving HTML without it")
        html = html.replace("{{BOOTSTRAP_JSON}}", bootstrap_json)
        html = html.replace("<!-- {{PHOTO_PRELOAD}} -->", preload)
        # no-store: the bootstrap embeds per-session auth state, so shared
        # caches must never store this response.
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store"})

    return app
