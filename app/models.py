"""ORM models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    jobs: Mapped[list[Job]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", lazy="selectin"
    )


class Job(Base):
    """One uploaded audio file and its transcription result."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error: Mapped[str] = mapped_column(Text, default="")

    language: Mapped[str] = mapped_column(String(12), default="")
    language_probability: Mapped[float] = mapped_column(Float, default=0.0)
    model_name: Mapped[str] = mapped_column(String(40), default="")
    full_text: Mapped[str] = mapped_column(Text, default="")

    # Aggregate quality signal, 0..1. Computed from segment confidences.
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    uncertain_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User] = relationship(back_populates="jobs")
    segments: Mapped[list[Segment]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Segment.index",
        lazy="selectin",
    )


class Segment(Base):
    """A timed chunk of transcript, with the model's own confidence in it."""

    __tablename__ = "segments"
    __table_args__ = (UniqueConstraint("job_id", "index", name="uq_segment_job_index"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)

    start: Mapped[float] = mapped_column(Float, default=0.0)
    end: Mapped[float] = mapped_column(Float, default=0.0)
    text: Mapped[str] = mapped_column(Text, default="")

    # Mean log-probability from Whisper. Negative; closer to 0 is better.
    avg_logprob: Mapped[float] = mapped_column(Float, default=0.0)
    # 0..1, derived from avg_logprob. This is what the UI colours.
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    no_speech_prob: Mapped[float] = mapped_column(Float, default=0.0)
    uncertain: Mapped[bool] = mapped_column(default=False)
    # Comma-separated words the model was least sure about, for the UI to
    # highlight. Empty when the line is clean.
    low_words: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[Job] = relationship(back_populates="segments")
