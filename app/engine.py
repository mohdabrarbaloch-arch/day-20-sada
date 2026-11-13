"""The transcription engine.

Wraps faster-whisper behind a small interface so the rest of the app never
imports it directly. The model is loaded lazily and cached — loading it takes
seconds and we do not want that on every request, nor at import time (which
would make the test suite download a model just to check a route).

Confidence comes from *word* probabilities, not the segment-level
avg_logprob. faster-whisper averages that over the whole 30-second decode
window, so every segment in one window reports the same value — which would
make the per-line confidence in the UI meaningless.
"""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.transcript import (
    aggregate_confidence,
    low_confidence_words,
    segment_confidence,
    segment_needs_review,
)

logger = logging.getLogger(__name__)


@dataclass
class RawSegment:
    index: int
    start: float
    end: float
    text: str
    avg_logprob: float
    no_speech_prob: float
    confidence: float
    uncertain: bool
    low_words: list[str] = field(default_factory=list)


@dataclass
class TranscriptionResult:
    language: str
    language_probability: float
    duration: float
    segments: list[RawSegment]
    full_text: str
    confidence: float
    uncertain_count: int
    model_name: str


class TranscriptionEngine:
    """Lazy, thread-safe wrapper around a faster-whisper model."""

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            from faster_whisper import WhisperModel

            logger.info(
                "loading whisper model=%s device=%s compute=%s",
                settings.whisper_model,
                settings.whisper_device,
                settings.whisper_compute_type,
            )
            self._model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
            return self._model

    def transcribe(
        self, audio_path: str | Path, *, language: str | None = None
    ) -> TranscriptionResult:
        """Transcribe a file. Blocking — call it from a worker thread."""
        model = self._load()
        segments_iter, info = model.transcribe(
            str(audio_path),
            beam_size=settings.whisper_beam_size,
            language=language or None,
            vad_filter=True,
            # 500ms was dropping the last word of a file: the trailing silence
            # got trimmed along with the word before it. 2000ms keeps the tail
            # intact and still removes long dead air.
            vad_parameters={"min_silence_duration_ms": 2000},
            word_timestamps=True,
        )

        raw: list[RawSegment] = []
        for i, seg in enumerate(segments_iter):
            text = (seg.text or "").strip()
            if not text:
                continue

            words = list(getattr(seg, "words", None) or [])
            word_probs = [float(w.probability) for w in words]
            word_pairs = [(w.word, float(w.probability)) for w in words]

            if word_probs:
                conf = segment_confidence(word_probs)
            else:
                # No word timings (rare) — fall back to the segment value.
                from app.transcript import logprob_to_confidence

                conf = logprob_to_confidence(seg.avg_logprob)

            no_speech = float(getattr(seg, "no_speech_prob", 0.0))
            raw.append(
                RawSegment(
                    index=i,
                    start=float(seg.start),
                    end=float(seg.end),
                    text=text,
                    avg_logprob=float(seg.avg_logprob),
                    no_speech_prob=no_speech,
                    confidence=conf,
                    uncertain=segment_needs_review(
                        conf, word_probs, no_speech, settings.low_confidence_threshold
                    ),
                    low_words=low_confidence_words(word_pairs),
                )
            )

        durations = [max(0.0, s.end - s.start) for s in raw]
        overall = aggregate_confidence([s.confidence for s in raw], durations)
        full_text = " ".join(s.text for s in raw).strip()

        return TranscriptionResult(
            language=getattr(info, "language", "") or "",
            language_probability=float(getattr(info, "language_probability", 0.0) or 0.0),
            duration=float(getattr(info, "duration", 0.0) or 0.0),
            segments=raw,
            full_text=full_text,
            confidence=overall,
            uncertain_count=sum(1 for s in raw if s.uncertain),
            model_name=settings.whisper_model,
        )


engine = TranscriptionEngine()
