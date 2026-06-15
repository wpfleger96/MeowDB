from __future__ import annotations

import logging

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from meowdb.api.routers import audio, ingest, meows, stats
from meowdb.config import CORS_ORIGINS, DATA_DIR, DB_PATH, MP3_DIR, STAGING_DIR, WAV_DIR

_STATIC_DIR = Path(__file__).parent.parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"
_logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    from meowdb.db import MeowDB

    if CORS_ORIGINS == ["*"]:
        _logger.warning("MEOWDB_CORS_ORIGINS='*' — all origins are allowed")
    elif not CORS_ORIGINS:
        _logger.warning(
            "MEOWDB_CORS_ORIGINS resolved to empty list — all cross-origin requests will be blocked"
        )

    for directory in (DATA_DIR, WAV_DIR, MP3_DIR, STAGING_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    app.state.db = MeowDB(DB_PATH)
    yield
    app.state.db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="MeowDB", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(meows.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(audio.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")

    @app.get("/health", include_in_schema=False, response_model=None)
    async def health(request: Request) -> JSONResponse:
        if not request.app.state.db.ping():
            return JSONResponse({"status": "error"}, status_code=503)
        return JSONResponse({"status": "ok"})

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_catch_all(full_path: str, request: Request) -> FileResponse:
        return FileResponse(str(_INDEX_HTML))

    return app
