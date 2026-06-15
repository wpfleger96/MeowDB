from __future__ import annotations

import logging
import time

import bcrypt

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from meowdb.config import IS_LOCALHOST, PASSWORD_HASH

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_failed_attempts: dict[str, tuple[int, float]] = {}
_MAX_ATTEMPTS = 5
_LOCKOUT_BASE_SECONDS = 30
_CLEANUP_THRESHOLD = 1000


def _client_ip(request: Request) -> str:
    if not IS_LOCALHOST:
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip:
            return cf_ip
    return request.client.host if request.client else "unknown"


def _check_lockout(ip: str) -> None:
    if ip not in _failed_attempts:
        return
    count, last_time = _failed_attempts[ip]
    if count < _MAX_ATTEMPTS:
        return
    exponent = min(count - _MAX_ATTEMPTS, 7)
    lockout_duration = min(_LOCKOUT_BASE_SECONDS * (2**exponent), 3600)
    if time.time() - last_time < lockout_duration:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
    _failed_attempts.pop(ip, None)


def _record_failure(ip: str) -> None:
    count = _failed_attempts.get(ip, (0, 0.0))[0]
    _failed_attempts[ip] = (count + 1, time.time())
    if len(_failed_attempts) > _CLEANUP_THRESHOLD:
        _cleanup_stale_entries()


def _record_success(ip: str) -> None:
    _failed_attempts.pop(ip, None)


def _cleanup_stale_entries() -> None:
    now = time.time()
    stale = [ip for ip, (_, ts) in _failed_attempts.items() if now - ts > 3600]
    for ip in stale:
        del _failed_attempts[ip]


async def require_auth(request: Request) -> None:
    if not PASSWORD_HASH and IS_LOCALHOST:
        return
    if not request.session.get("authenticated"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> dict[str, str]:
    ip = _client_ip(request)
    _check_lockout(ip)

    if not PASSWORD_HASH:
        raise HTTPException(status_code=503, detail="Authentication not configured")

    try:
        valid = await run_in_threadpool(
            bcrypt.checkpw, body.password.encode(), PASSWORD_HASH.encode()
        )
    except ValueError:
        valid = False

    if valid:
        _record_success(ip)
        request.session["authenticated"] = True
        _logger.info("Login success from %s", ip)
        return {"status": "ok"}

    _record_failure(ip)
    _logger.warning("Login failure from %s (attempt %d)", ip, _failed_attempts.get(ip, (0,))[0])
    raise HTTPException(status_code=401, detail="Invalid password")


@router.post("/logout")
async def logout(request: Request) -> dict[str, str]:
    request.session.clear()
    return {"status": "ok"}


@router.get("/status")
async def auth_status(request: Request) -> dict[str, bool]:
    return {
        "authenticated": bool(request.session.get("authenticated", False)),
        "auth_required": bool(PASSWORD_HASH) or not IS_LOCALHOST,
    }
