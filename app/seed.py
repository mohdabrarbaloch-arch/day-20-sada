"""Seed a demo account so the landing page's "use the demo account" works.

Idempotent — safe to run on every boot.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import User
from app.security import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

DEMO_EMAIL = "demo@sada.app"
DEMO_PASSWORD = "demo12345"


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing:
            logger.info("demo account already exists")
            return
        db.add(
            User(
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                display_name="Demo",
            )
        )
        db.commit()
        logger.info("created demo account %s", DEMO_EMAIL)
    finally:
        db.close()


if __name__ == "__main__":
    main()
