"""Transcription job routes: upload, list, detail, export, delete."""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.deps import current_user
from app.engine import engine
from app.limiter import limiter
from app.models import Job, Segment, User
from app.schemas import JobDetail, JobListResponse, JobSummary
from app.transcript import (
    CONTENT_TYPES,
    FORMATTERS,
    SegmentData,
    render,
    safe_filename,
    validate_upload,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])

CHUNK = 1024 * 1024


def _owned_job(job_id: str, user: User, db: Session) -> Job:
    """Fetch a job the caller owns.

    Returns 404 rather than 403 for someone else's job — a 403 would confirm
    the id exists, which is information the caller has no business having.
    """
    job = db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


def _run_transcription(job_id: str) -> None:
    """Background worker. Opens its own session — the request's is closed."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        job.status = "running"
        db.commit()

        try:
            result = engine.transcribe(job.stored_path)
        except Exception as exc:  # noqa: BLE001 - surface any engine failure to the user
            logger.exception("transcription failed for job %s", job_id)
            job.status = "failed"
            job.error = f"Transcription failed: {exc.__class__.__name__}"
            job.completed_at = datetime.now(UTC)
            db.commit()
            return

        job.language = result.language
        job.language_probability = result.language_probability
        job.duration_seconds = result.duration
        job.full_text = result.full_text
        job.confidence = result.confidence
        job.uncertain_count = result.uncertain_count
        job.model_name = result.model_name
        job.status = "done"
        job.completed_at = datetime.now(UTC)

        for seg in result.segments:
            db.add(
                Segment(
                    job_id=job.id,
                    index=seg.index,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    avg_logprob=seg.avg_logprob,
                    confidence=seg.confidence,
                    no_speech_prob=seg.no_speech_prob,
                    uncertain=seg.uncertain,
                    low_words=", ".join(seg.low_words),
                )
            )
        db.commit()
    finally:
        db.close()


@router.post("", response_model=JobSummary, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.rate_limit_transcribe)
async def create_job(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    language: str | None = Query(default=None, max_length=12),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobSummary:
    """Accept an audio file and queue it for transcription."""
    filename = safe_filename(file.filename or "")
    content_type = file.content_type or ""

    # Read in chunks so a 100 MB upload never lands in memory whole, and stop
    # the moment the cap is crossed rather than after writing the whole file.
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    ext = Path(filename).suffix.lower() or ".bin"
    dest = settings.upload_dir / f"{job_id}{ext}"

    size = 0
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File is larger than the {settings.max_upload_mb} MB limit.",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        logger.exception("could not store upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not store the uploaded file.",
        ) from exc

    problem = validate_upload(filename, content_type, size, settings.max_upload_mb)
    if problem:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=problem)

    job = Job(
        id=job_id,
        user_id=user.id,
        original_filename=filename,
        stored_path=str(dest),
        content_type=content_type,
        size_bytes=size,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background.add_task(_run_transcription, job.id)
    return JobSummary.model_validate(job)


@router.get("", response_model=JobListResponse)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobListResponse:
    total = db.scalar(select(func.count(Job.id)).where(Job.user_id == user.id)) or 0
    rows = db.scalars(
        select(Job)
        .where(Job.user_id == user.id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return JobListResponse(items=[JobSummary.model_validate(r) for r in rows], total=total)


@router.get("/{job_id}", response_model=JobDetail)
def get_job(
    job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> JobDetail:
    job = _owned_job(job_id, user, db)
    return JobDetail.model_validate(job)


@router.get("/{job_id}/export", response_class=PlainTextResponse)
def export_job(
    job_id: str,
    fmt: str = Query(default="txt", pattern="^(srt|vtt|txt|md)$"),
    timestamps: bool = Query(default=False),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    job = _owned_job(job_id, user, db)
    if job.status != "done":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is {job.status}; nothing to export yet.",
        )

    segments = [
        SegmentData(
            index=s.index,
            start=s.start,
            end=s.end,
            text=s.text,
            confidence=s.confidence,
            uncertain=s.uncertain,
        )
        for s in job.segments
    ]
    if fmt == "txt":
        body = render(segments, "txt", title=job.original_filename)
        if timestamps:
            from app.transcript import to_txt

            body = to_txt(segments, timestamps=True)
    else:
        body = render(segments, fmt, title=job.original_filename)

    stem = Path(job.original_filename).stem or "transcript"
    return PlainTextResponse(
        content=body,
        media_type=CONTENT_TYPES[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.{fmt}"',
            "X-Formats-Available": ",".join(sorted(FORMATTERS)),
        },
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    job = _owned_job(job_id, user, db)
    Path(job.stored_path).unlink(missing_ok=True)
    db.delete(job)
    db.commit()
