"""Password hashing and JWT handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

# bcrypt silently truncates at 72 bytes. Reject longer input rather than
# letting two different passwords hash to the same value.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        raw = password.encode("utf-8")
        if len(raw) > MAX_PASSWORD_BYTES:
            return False
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.resolved_jwt_secret(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Return the user id, or None if the token is invalid or expired."""
    try:
        payload = jwt.decode(
            token,
            settings.resolved_jwt_secret(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) and sub else None
