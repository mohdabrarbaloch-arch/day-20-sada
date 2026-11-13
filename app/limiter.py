"""Rate limiter instance, kept separate so routers can import it without cycles."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    storage_uri="memory://",
    enabled=settings.rate_limit_enabled,
)
