"""Pure transcription logic: confidence scoring and export formatting.

Deliberately free of FastAPI, SQLAlchemy and Whisper imports so it can be
tested without a model, a database or a network. Everything here is a pure
function of its arguments.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# Whisper reports mean log-probability per segment. In practice:
#   -0.05  near-certain
#   -0.30  solid
#   -0.75  shaky
#   -1.50  guessing
# We map that range onto 0..1 with a logistic curve so the UI has something
# human-readable to colour, while keeping the raw value for anyone who wants it.
_LOGPROB_FLOOR = -1.5
_LOGPROB_CEIL = 0.0


def logprob_to_confidence(avg_logprob: float) -> float:
    """Map Whisper's mean log-probability onto a 0..1 confidence score.

    Clamped at both ends. A segment at -0.05 lands around 0.97; one at -1.5
    lands at 0.0. The curve is logistic rather than linear because the useful
    discrimination happens in the middle of the range, not at the extremes.
    """
    if avg_logprob is None or math.isnan(avg_logprob):
        return 0.0
    value = float(avg_logprob)
    # Pin the ends exactly. The logistic below never quite reaches 0 or 1, and
    # a segment at the floor should read as "no confidence at all", not 0.018.
    if value <= _LOGPROB_FLOOR:
        return 0.0
    if value >= _LOGPROB_CEIL:
        return 1.0
    # Normalise to 0..1, then bend it so mid-range values spread out.
    x = (value - _LOGPROB_FLOOR) / (_LOGPROB_CEIL - _LOGPROB_FLOOR)
    # Logistic centred at 0.5 with a gentle slope.
    return round(1.0 / (1.0 + math.exp(-8.0 * (x - 0.5))), 4)


def is_uncertain(avg_logprob: float, no_speech_prob: float, threshold: float) -> bool:
    """Should this segment be flagged for a human to check?

    Two independent reasons to doubt a segment: the model was unsure of the
    words, or it suspected there was no speech there at all. The second one
    matters because Whisper will happily transcribe silence into plausible
    text, and that text is the most dangerous kind of wrong.
    """
    if avg_logprob < threshold:
        return True
    return no_speech_prob > 0.6


# --- word-level confidence ---------------------------------------------
#
# faster-whisper's segment-level avg_logprob is averaged over the whole 30s
# decode window, so consecutive segments in one window come back with the
# *same* number to many decimal places. That is useless for pointing at a
# specific line. Word probabilities are per-token and genuinely differ, so
# that is what the UI is built on.

# A word below this is worth showing to the user.
WORD_LOW_THRESHOLD = 0.5
# A segment whose worst word is below this gets flagged even if the average
# looks fine — one badly wrong word can change the meaning of a sentence.
WORD_MIN_THRESHOLD = 0.35


def segment_confidence(word_probs: list[float]) -> float:
    """Confidence for a segment, from its word probabilities.

    Uses the mean, but pulled down by the worst word: a sentence where every
    word is 0.99 except one at 0.05 is not a 0.9 sentence. The blend is 70/30
    toward the mean so a single odd token does not dominate a long line.
    """
    if not word_probs:
        return 0.0
    mean = sum(word_probs) / len(word_probs)
    worst = min(word_probs)
    blended = 0.7 * mean + 0.3 * worst
    return round(max(0.0, min(1.0, blended)), 4)


def low_confidence_words(
    words: list[tuple[str, float]], threshold: float = WORD_LOW_THRESHOLD
) -> list[str]:
    """The words in a segment the model was least sure about, in order."""
    return [w.strip() for w, p in words if p < threshold and w.strip()]


def segment_needs_review(
    confidence: float,
    word_probs: list[float],
    no_speech_prob: float,
    threshold: float,
) -> bool:
    """Flag a segment if the average is low, the worst word is very low, or
    the model suspected there was no speech at all."""
    if confidence < threshold:
        return True
    if word_probs and min(word_probs) < WORD_MIN_THRESHOLD:
        return True
    return no_speech_prob > 0.6


def aggregate_confidence(confidences: list[float], weights: list[float] | None = None) -> float:
    """Overall transcript confidence.

    Weighted by segment duration when weights are supplied, because a
    two-second mumble should not drag down a five-minute clear recording.
    """
    if not confidences:
        return 0.0
    if weights is None or len(weights) != len(confidences):
        return round(sum(confidences) / len(confidences), 4)
    total_weight = sum(weights)
    if total_weight <= 0:
        return round(sum(confidences) / len(confidences), 4)
    weighted = sum(c * w for c, w in zip(confidences, weights, strict=True))
    return round(weighted / total_weight, 4)


@dataclass(frozen=True)
class SegmentData:
    """A segment as the formatters need it — no ORM, no model objects."""

    index: int
    start: float
    end: float
    text: str
    confidence: float = 1.0
    uncertain: bool = False


def _timestamp(seconds: float, *, comma: bool = True) -> str:
    """Format seconds as HH:MM:SS,mmm (SRT) or HH:MM:SS.mmm (VTT)."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    sep = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def to_srt(segments: list[SegmentData]) -> str:
    """SubRip. The format every video editor and YouTube accepts."""
    blocks = []
    for i, seg in enumerate(segments, start=1):
        text = seg.text.strip()
        if not text:
            continue
        blocks.append(f"{i}\n{_timestamp(seg.start)} --> {_timestamp(seg.end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_vtt(segments: list[SegmentData]) -> str:
    """WebVTT. Needs the header and dot-separated milliseconds."""
    lines = ["WEBVTT", ""]
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        lines.append(f"{_timestamp(seg.start, comma=False)} --> {_timestamp(seg.end, comma=False)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def to_txt(segments: list[SegmentData], *, timestamps: bool = False) -> str:
    """Plain text. Timestamps optional — most people just want the words."""
    out = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if timestamps:
            out.append(f"[{_timestamp(seg.start, comma=False)}] {text}")
        else:
            out.append(text)
    if timestamps:
        return "\n".join(out) + ("\n" if out else "")
    # Join into paragraphs rather than one line per segment — segments break
    # mid-sentence and a wall of short lines is unreadable.
    return _reflow(out)


def _reflow(lines: list[str]) -> str:
    """Join segment lines into readable paragraphs."""
    if not lines:
        return ""
    joined = " ".join(line.strip() for line in lines)
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined + "\n"


def to_markdown(segments: list[SegmentData], *, title: str = "Transcript") -> str:
    """Markdown with uncertain segments marked, for review workflows."""
    out = [f"# {title}", ""]
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        stamp = _timestamp(seg.start, comma=False)
        if seg.uncertain:
            out.append(f"- **`{stamp}`** {text}  _⚠ check this line_")
        else:
            out.append(f"- `{stamp}` {text}")
    return "\n".join(out) + "\n"


FORMATTERS = {
    "srt": to_srt,
    "vtt": to_vtt,
    "txt": to_txt,
    "md": to_markdown,
}

CONTENT_TYPES = {
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


def render(segments: list[SegmentData], fmt: str, *, title: str = "Transcript") -> str:
    """Render segments in the requested format. Raises ValueError if unknown."""
    key = fmt.lower().strip()
    if key not in FORMATTERS:
        raise ValueError(f"unsupported format: {fmt!r} (expected one of {sorted(FORMATTERS)})")
    if key == "md":
        return to_markdown(segments, title=title)
    return FORMATTERS[key](segments)


# --- audio validation ---------------------------------------------------

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".opus",
    ".webm",
    ".aac",
    ".mp4",
    ".mpeg",
    ".mpga",
}

AUDIO_MIME_PREFIXES = ("audio/", "video/")


def validate_upload(filename: str, content_type: str, size_bytes: int, max_mb: int) -> str | None:
    """Return an error message, or None if the upload is acceptable.

    Extension and MIME are both checked because either alone is trivially
    spoofed, and the size cap is enforced here as well as at the ASGI layer.
    """
    if not filename:
        return "A filename is required."
    if size_bytes <= 0:
        return "The uploaded file is empty."
    if size_bytes > max_mb * 1024 * 1024:
        return f"File is larger than the {max_mb} MB limit."

    lowered = filename.lower()
    ext = "." + lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    if ext not in AUDIO_EXTENSIONS:
        return (
            f"Unsupported file type {ext or '(none)'}. "
            f"Accepted: {', '.join(sorted(AUDIO_EXTENSIONS))}"
        )

    ct = (content_type or "").lower().split(";")[0].strip()
    if (
        ct
        and ct not in {"application/octet-stream", "binary/octet-stream"}
        and not ct.startswith(AUDIO_MIME_PREFIXES)
    ):
        return f"Unsupported content type {ct!r}."
    return None


def safe_filename(filename: str) -> str:
    """Strip any path components and dangerous characters from a filename."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    if not base:
        base = "audio"
    return base[:120]
