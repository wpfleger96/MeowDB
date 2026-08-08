from __future__ import annotations

import io
import warnings

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest

from moto import mock_aws
from PIL import Image

from meowdb import config
from meowdb.api.app import create_app
from meowdb.storage import reset_s3_client

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from starlette.testclient import TestClient

_S3_BUCKET = "test-meowdb"
_S3_REGION = "us-east-1"


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "black").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite"


@pytest.fixture
def s3_state(monkeypatch):
    """Activate moto mock_aws, patch config for S3 mode, create test bucket.

    Yields the moto boto3 S3 client so tests can inspect bucket contents.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _S3_REGION)
    monkeypatch.setattr(config, "S3_BUCKET", _S3_BUCKET)
    monkeypatch.setattr(config, "S3_REGION", _S3_REGION)
    monkeypatch.setattr(config, "S3_ACCESS_KEY_ID", None)
    monkeypatch.setattr(config, "S3_SECRET_ACCESS_KEY", None)
    monkeypatch.setattr(config, "S3_ENDPOINT_URL", None)

    with mock_aws():
        reset_s3_client()
        s3 = boto3.client("s3", region_name=_S3_REGION)
        s3.create_bucket(Bucket=_S3_BUCKET)
        yield s3
    reset_s3_client()


@pytest.fixture
def s3_api_client(s3_state, tmp_path):
    """FastAPI TestClient in S3 mode backed by the active moto mock.

    Yields (TestClient, app, s3_boto3_client).
    """
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    photos_dir = tmp_path / "photos"
    staging_dir = tmp_path / "staging"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html></html>")

    patches = [
        patch("meowdb.api.app.DB_PATH", tmp_path / "test.sqlite"),
        patch("meowdb.api.app.DATA_DIR", tmp_path),
        patch("meowdb.api.app.WAV_DIR", wav_dir),
        patch("meowdb.api.app.MP3_DIR", mp3_dir),
        patch("meowdb.api.app.STAGING_DIR", staging_dir),
        patch("meowdb.api.app._STATIC_DIR", static_dir),
        patch("meowdb.api.app._INDEX_HTML", static_dir / "index.html"),
        patch("meowdb.api.routers.ingest.STAGING_DIR", staging_dir),
        patch("meowdb.api.routers.ingest.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.ingest.MP3_DIR", mp3_dir),
        patch("meowdb.api.routers.audio.MP3_DIR", mp3_dir),
        patch("meowdb.api.routers.audio.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.meows.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.meows.MP3_DIR", mp3_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", True),
    ]

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            app = create_app()
            with TestClient(app, raise_server_exceptions=True) as tc:
                yield tc, app, s3_state
