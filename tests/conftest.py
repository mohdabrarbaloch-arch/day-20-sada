"""Shared test fixtures.

The database is a throwaway SQLite file per test session, and the Whisper
engine is never loaded — every test here runs offline in well under a second.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="sada-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["UPLOAD_DIR"] = f"{_TMP}/uploads"
os.environ["JWT_SECRET"] = "test-secret-not-used-anywhere-real"
os.environ["ENVIRONMENT"] = "test"
os.environ["RATE_LIMIT_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user_token(client: TestClient) -> str:
    import uuid

    email = f"u{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": "Test"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(user_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def tmp_audio(tmp_path: Path) -> Path:
    """A tiny valid-looking WAV. Never actually transcribed in tests."""
    p = tmp_path / "sample.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 200)
    return p
