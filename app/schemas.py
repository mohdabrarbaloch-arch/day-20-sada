"""Request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(default="", max_length=80)

    @field_validator("password")
    @classmethod
    def _password_bytes(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    start: float
    end: float
    text: str
    confidence: float
    avg_logprob: float
    no_speech_prob: float
    uncertain: bool
    low_words: str = ""


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    status: str
    language: str
    language_probability: float
    duration_seconds: float
    size_bytes: int
    confidence: float
    uncertain_count: int
    model_name: str
    created_at: datetime
    completed_at: datetime | None = None


class JobDetail(JobSummary):
    full_text: str
    error: str
    segments: list[SegmentOut] = Field(default_factory=list)


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int


class HealthResponse(BaseModel):
    status: str
    version: str
    model: str
    engine_ready: bool
