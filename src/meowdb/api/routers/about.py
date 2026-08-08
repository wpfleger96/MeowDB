from __future__ import annotations

import os
import platform
import sqlite3
import time

from fastapi import APIRouter
from pydantic import BaseModel

from meowdb import __version__
from meowdb.config import IS_LOCALHOST, PASSWORD_HASH

# Module import happens during create_app(), so this is effectively process start.
_STARTUP_TIME: float = time.monotonic()

router = APIRouter(tags=["about"])


class AboutInfo(BaseModel):
    version: str
    git_sha: str
    build_time: str
    uptime_seconds: float
    auth_mode: str
    python_version: str
    sqlite_version: str


@router.get("/about", include_in_schema=False)
async def get_about() -> AboutInfo:
    auth_required = bool(PASSWORD_HASH) or not IS_LOCALHOST
    return AboutInfo(
        version=__version__,
        git_sha=os.environ.get("MEOWDB_GIT_SHA", "dev"),
        build_time=os.environ.get("MEOWDB_BUILD_TIME", ""),
        uptime_seconds=round(time.monotonic() - _STARTUP_TIME, 1),
        auth_mode="Password-protected" if auth_required else "Open (local)",
        python_version=platform.python_version(),
        sqlite_version=sqlite3.sqlite_version,
    )
