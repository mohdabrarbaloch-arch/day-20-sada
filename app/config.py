"""Application settings, loaded from the environment only.

Nothing here has a secret default. If a value is missing the app refuses to
start in production rather than quietly falling back to something insecure.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Sada"
    environment: str = "development"
    debug: bool = False

    # --- security -------------------------------------------------------
    # Generated per-process in development so a fresh clone just works.
    # In production this MUST come from the environment.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    bcrypt_rounds: int = 12

    # --- storage --------------------------------------------------------
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'sada.db'}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    max_upload_mb: int = 100

    # --- transcription --------------------------------------------------
    whisper_model: str = "tiny"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 5
    # Segments below this average log-probability get flagged as uncertain.
    low_confidence_threshold: float = -0.75

    # --- limits ---------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_transcribe: str = "10/minute"
    rate_limit_default: str = "120/minute"
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def resolved_jwt_secret(self) -> str:
        """Return the configured secret, or a throwaway one in development."""
        if self.jwt_secret:
            return self.jwt_secret
        if self.is_production:
            raise RuntimeError(
                "JWT_SECRET must be set in production. "
                'Generate one with: python -c "import secrets;print(secrets.token_urlsafe(48))"'
            )
        return _DEV_SECRET


_DEV_SECRET = secrets.token_urlsafe(48)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
