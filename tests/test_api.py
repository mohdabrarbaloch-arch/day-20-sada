"""API tests: auth, ownership isolation, upload validation, export."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


class TestHealth:
    def test_health_ok(self, client: TestClient):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["engine_ready"] is False  # never loaded in tests

    def test_security_headers_present(self, client: TestClient):
        r = client.get("/api/health")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"


class TestAuth:
    def test_register_returns_token(self, client: TestClient):
        email = f"{uuid.uuid4().hex[:8]}@example.com"
        r = client.post("/api/auth/register", json={"email": email, "password": "longenough123"})
        assert r.status_code == 201
        assert r.json()["access_token"]
        assert r.json()["user"]["email"] == email

    def test_duplicate_email_conflicts(self, client: TestClient):
        email = f"{uuid.uuid4().hex[:8]}@example.com"
        payload = {"email": email, "password": "longenough123"}
        assert client.post("/api/auth/register", json=payload).status_code == 201
        assert client.post("/api/auth/register", json=payload).status_code == 409

    def test_short_password_rejected(self, client: TestClient):
        r = client.post(
            "/api/auth/register",
            json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "password": "short"},
        )
        assert r.status_code == 422

    def test_login_wrong_password_is_401(self, client: TestClient):
        email = f"{uuid.uuid4().hex[:8]}@example.com"
        client.post("/api/auth/register", json={"email": email, "password": "longenough123"})
        r = client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
        assert r.status_code == 401

    def test_login_unknown_email_same_message(self, client: TestClient):
        r = client.post(
            "/api/auth/login",
            json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "password": "whatever123"},
        )
        assert r.status_code == 401
        # Must not reveal whether the address exists.
        assert r.json()["detail"] == "Incorrect email or password."

    def test_me_requires_auth(self, client: TestClient):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_token(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert "@example.com" in r.json()["email"]

    def test_garbage_token_rejected(self, client: TestClient):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.token"})
        assert r.status_code == 401


class TestJobsAuth:
    def test_list_requires_auth(self, client: TestClient):
        assert client.get("/api/jobs").status_code == 401

    def test_upload_requires_auth(self, client: TestClient, tmp_audio):
        with tmp_audio.open("rb") as fh:
            r = client.post("/api/jobs", files={"file": ("a.wav", fh, "audio/wav")})
        assert r.status_code == 401

    def test_empty_list_for_new_user(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/jobs", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"items": [], "total": 0}


class TestUploadValidation:
    def test_rejects_non_audio_extension(self, client: TestClient, auth_headers: dict):
        r = client.post(
            "/api/jobs",
            headers=auth_headers,
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 415
        assert "Unsupported" in r.json()["detail"]

    def test_rejects_empty_file(self, client: TestClient, auth_headers: dict):
        r = client.post(
            "/api/jobs",
            headers=auth_headers,
            files={"file": ("empty.mp3", b"", "audio/mpeg")},
        )
        assert r.status_code == 415

    def test_accepts_valid_audio(self, client: TestClient, auth_headers: dict, tmp_audio):
        with tmp_audio.open("rb") as fh:
            r = client.post(
                "/api/jobs",
                headers=auth_headers,
                files={"file": ("sample.wav", fh, "audio/wav")},
            )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] in {"queued", "running", "done", "failed"}
        assert body["original_filename"] == "sample.wav"


class TestOwnershipIsolation:
    def test_other_users_job_is_404_not_403(
        self, client: TestClient, auth_headers: dict, tmp_audio
    ):
        with tmp_audio.open("rb") as fh:
            created = client.post(
                "/api/jobs",
                headers=auth_headers,
                files={"file": ("mine.wav", fh, "audio/wav")},
            )
        job_id = created.json()["id"]

        other = client.post(
            "/api/auth/register",
            json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "password": "longenough123"},
        ).json()["access_token"]

        r = client.get(f"/api/jobs/{job_id}", headers={"Authorization": f"Bearer {other}"})
        # 404, not 403 — a 403 would confirm the id exists.
        assert r.status_code == 404

    def test_unknown_job_is_404(self, client: TestClient, auth_headers: dict):
        assert client.get("/api/jobs/deadbeef", headers=auth_headers).status_code == 404

    def test_delete_unknown_is_404(self, client: TestClient, auth_headers: dict):
        assert client.delete("/api/jobs/deadbeef", headers=auth_headers).status_code == 404


class TestExport:
    def test_export_before_done_is_409(self, client: TestClient, auth_headers: dict, tmp_audio):
        with tmp_audio.open("rb") as fh:
            job = client.post(
                "/api/jobs",
                headers=auth_headers,
                files={"file": ("x.wav", fh, "audio/wav")},
            ).json()
        r = client.get(f"/api/jobs/{job['id']}/export?fmt=srt", headers=auth_headers)
        # Either still processing (409) or already failed on the fake WAV (409).
        assert r.status_code == 409

    def test_bad_format_is_422(self, client: TestClient, auth_headers: dict, tmp_audio):
        with tmp_audio.open("rb") as fh:
            job = client.post(
                "/api/jobs",
                headers=auth_headers,
                files={"file": ("y.wav", fh, "audio/wav")},
            ).json()
        r = client.get(f"/api/jobs/{job['id']}/export?fmt=docx", headers=auth_headers)
        assert r.status_code == 422
