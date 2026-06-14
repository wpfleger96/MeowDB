from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from meowdb.api.routers import audio, ingest, meows, stats
from meowdb.config import DATA_DIR, DB_PATH, MP3_DIR, STAGING_DIR, WAV_DIR

_STATIC_DIR = Path(__file__).parent.parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    from meowdb.db import MeowDB

    for directory in (DATA_DIR, WAV_DIR, MP3_DIR, STAGING_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    app.state.db = MeowDB(DB_PATH)
    yield
    app.state.db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="MeowDB", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(meows.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(audio.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_catch_all(full_path: str, request: Request) -> FileResponse:
        return FileResponse(str(_INDEX_HTML))

    return app
