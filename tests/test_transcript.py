"""Tests for the pure transcription logic — confidence, exports, validation."""

from __future__ import annotations

import pytest

from app.transcript import (
    SegmentData,
    aggregate_confidence,
    is_uncertain,
    logprob_to_confidence,
    render,
    safe_filename,
    to_markdown,
    to_srt,
    to_txt,
    to_vtt,
    validate_upload,
)


class TestConfidenceMapping:
    def test_near_certain_logprob_maps_high(self):
        assert logprob_to_confidence(-0.05) > 0.9

    def test_guessing_logprob_maps_low(self):
        assert logprob_to_confidence(-1.4) < 0.1

    def test_midpoint_is_around_half(self):
        # -0.75 is the documented "shaky" point; it should sit near the middle.
        assert 0.4 < logprob_to_confidence(-0.75) < 0.6

    def test_monotonic(self):
        values = [logprob_to_confidence(x) for x in (-1.5, -1.0, -0.5, -0.1, 0.0)]
        assert values == sorted(values)

    def test_clamped_below_floor(self):
        assert logprob_to_confidence(-99.0) == 0.0

    def test_clamped_above_ceiling(self):
        assert logprob_to_confidence(5.0) == 1.0

    def test_nan_is_zero(self):
        assert logprob_to_confidence(float("nan")) == 0.0


class TestUncertainty:
    def test_low_logprob_flags(self):
        assert is_uncertain(-1.2, 0.0, -0.75) is True

    def test_high_logprob_does_not_flag(self):
        assert is_uncertain(-0.1, 0.0, -0.75) is False

    def test_silence_suspicion_flags_even_when_confident(self):
        # Whisper transcribing silence into plausible text is the dangerous
        # case: the words look confident but there was nothing there.
        assert is_uncertain(-0.05, 0.9, -0.75) is True

    def test_threshold_is_respected(self):
        assert is_uncertain(-0.5, 0.0, -0.4) is True
        assert is_uncertain(-0.5, 0.0, -0.6) is False


class TestAggregate:
    def test_empty_is_zero(self):
        assert aggregate_confidence([]) == 0.0

    def test_plain_mean_without_weights(self):
        assert aggregate_confidence([1.0, 0.0]) == 0.5

    def test_duration_weighting_lets_long_segment_dominate(self):
        # A 2s mumble at 0.0 should not drag down a 100s clear passage at 1.0.
        result = aggregate_confidence([1.0, 0.0], [100.0, 2.0])
        assert result > 0.97

    def test_zero_total_weight_falls_back_to_mean(self):
        assert aggregate_confidence([0.4, 0.6], [0.0, 0.0]) == 0.5

    def test_mismatched_weights_fall_back_to_mean(self):
        assert aggregate_confidence([0.2, 0.4], [1.0]) == 0.3


class TestSrt:
    def test_basic_block(self):
        segs = [SegmentData(0, 0.0, 2.5, "Hello there.")]
        out = to_srt(segs)
        assert out.startswith("1\n00:00:00,000 --> 00:00:02,500\nHello there.")

    def test_indexes_are_sequential_from_one(self):
        segs = [SegmentData(i, i * 1.0, i * 1.0 + 1.0, f"line {i}") for i in range(3)]
        out = to_srt(segs)
        assert out.count("-->") == 3
        assert out.split("\n\n")[0].startswith("1\n")
        assert out.split("\n\n")[2].startswith("3\n")

    def test_empty_segments_are_skipped(self):
        segs = [SegmentData(0, 0.0, 1.0, "   "), SegmentData(1, 1.0, 2.0, "real")]
        out = to_srt(segs)
        assert out.count("-->") == 1
        assert "real" in out

    def test_hours_roll_over(self):
        segs = [SegmentData(0, 3661.5, 3662.0, "late")]
        assert "01:01:01,500" in to_srt(segs)

    def test_empty_input_gives_empty_string(self):
        assert to_srt([]) == ""


class TestVtt:
    def test_has_header(self):
        assert to_vtt([SegmentData(0, 0.0, 1.0, "hi")]).startswith("WEBVTT")

    def test_uses_dots_not_commas(self):
        out = to_vtt([SegmentData(0, 0.0, 1.5, "hi")])
        assert "00:00:01.500" in out
        assert "00:00:01,500" not in out


class TestTxt:
    def test_reflows_into_one_paragraph(self):
        segs = [SegmentData(0, 0.0, 1.0, "The cat"), SegmentData(1, 1.0, 2.0, "sat down.")]
        assert to_txt(segs) == "The cat sat down.\n"

    def test_timestamps_option(self):
        segs = [SegmentData(0, 0.0, 1.0, "hello")]
        out = to_txt(segs, timestamps=True)
        assert out.startswith("[00:00:00.000] hello")

    def test_empty(self):
        assert to_txt([]) == ""


class TestMarkdown:
    def test_uncertain_lines_are_marked(self):
        segs = [
            SegmentData(0, 0.0, 1.0, "clear", uncertain=False),
            SegmentData(1, 1.0, 2.0, "mumbled", uncertain=True),
        ]
        out = to_markdown(segs)
        assert "check this line" in out
        assert out.count("check this line") == 1


class TestRender:
    def test_dispatches_all_formats(self):
        segs = [SegmentData(0, 0.0, 1.0, "x")]
        for fmt in ("srt", "vtt", "txt", "md"):
            assert render(segs, fmt)

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="unsupported format"):
            render([], "docx")

    def test_case_insensitive(self):
        assert render([SegmentData(0, 0.0, 1.0, "x")], "SRT").startswith("1\n")


class TestUploadValidation:
    def test_accepts_mp3(self):
        assert validate_upload("talk.mp3", "audio/mpeg", 1000, 100) is None

    def test_rejects_exe(self):
        err = validate_upload("virus.exe", "application/x-msdownload", 1000, 100)
        assert err and "Unsupported file type" in err

    def test_rejects_empty_file(self):
        assert "empty" in (validate_upload("a.mp3", "audio/mpeg", 0, 100) or "")

    def test_rejects_oversize(self):
        err = validate_upload("a.mp3", "audio/mpeg", 200 * 1024 * 1024, 100)
        assert err and "larger than" in err

    def test_rejects_wrong_mime(self):
        err = validate_upload("a.mp3", "text/html", 1000, 100)
        assert err and "content type" in err

    def test_allows_octet_stream(self):
        # Browsers send this for some audio; the extension check still applies.
        assert validate_upload("a.wav", "application/octet-stream", 1000, 100) is None

    def test_rejects_missing_filename(self):
        assert validate_upload("", "audio/mpeg", 1000, 100) is not None


class TestSafeFilename:
    def test_strips_path_traversal(self):
        assert safe_filename("../../etc/passwd") == "passwd"

    def test_strips_windows_path(self):
        assert safe_filename("C:\\Users\\x\\a.mp3") == "a.mp3"

    def test_replaces_spaces_and_symbols(self):
        assert safe_filename("my file (1).mp3") == "my_file__1_.mp3"

    def test_empty_becomes_audio(self):
        assert safe_filename("...") == "audio"

    def test_truncates_long_names(self):
        assert len(safe_filename("a" * 500 + ".mp3")) <= 120
