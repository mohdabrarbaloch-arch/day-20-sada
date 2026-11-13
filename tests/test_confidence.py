"""Tests for word-level confidence — the part the UI is actually built on."""

from __future__ import annotations

from app.transcript import (
    WORD_LOW_THRESHOLD,
    WORD_MIN_THRESHOLD,
    low_confidence_words,
    segment_confidence,
    segment_needs_review,
)


class TestSegmentConfidence:
    def test_all_certain_words(self):
        assert segment_confidence([0.99, 0.98, 0.97]) > 0.95

    def test_all_terrible_words(self):
        assert segment_confidence([0.1, 0.1, 0.1]) < 0.15

    def test_one_bad_word_pulls_the_line_down(self):
        # 9 good words and 1 at 0.05 should not read as a 0.9 line.
        probs = [0.99] * 9 + [0.05]
        conf = segment_confidence(probs)
        assert conf < 0.85
        assert conf > 0.5  # but not destroyed either

    def test_empty_is_zero(self):
        assert segment_confidence([]) == 0.0

    def test_bounded(self):
        assert 0.0 <= segment_confidence([0.0, 0.0]) <= 1.0
        assert 0.0 <= segment_confidence([1.0, 1.0]) <= 1.0

    def test_worst_word_has_real_weight(self):
        # Same mean, different worst word — the one with the bad word must
        # score lower. This is the property the whole design rests on.
        a = segment_confidence([0.9, 0.9, 0.9])
        b = segment_confidence([1.0, 1.0, 0.7])
        assert b < a


class TestLowConfidenceWords:
    def test_picks_words_below_threshold(self):
        words = [("Karachi", 0.99), ("harbor", 0.45), ("stalls", 0.23)]
        assert low_confidence_words(words) == ["harbor", "stalls"]

    def test_empty_when_all_confident(self):
        assert low_confidence_words([("a", 0.99), ("b", 0.95)]) == []

    def test_strips_whitespace(self):
        assert low_confidence_words([("  word  ", 0.1)]) == ["word"]

    def test_skips_blank_tokens(self):
        assert low_confidence_words([("   ", 0.1)]) == []

    def test_custom_threshold(self):
        words = [("a", 0.6), ("b", 0.4)]
        assert low_confidence_words(words, threshold=0.7) == ["a", "b"]
        assert low_confidence_words(words, threshold=0.3) == []

    def test_preserves_order(self):
        words = [("z", 0.1), ("a", 0.2), ("m", 0.3)]
        assert low_confidence_words(words) == ["z", "a", "m"]


class TestSegmentNeedsReview:
    def test_low_average_flags(self):
        assert segment_needs_review(0.3, [0.3, 0.3], 0.0, 0.5) is True

    def test_high_average_clean_words_passes(self):
        assert segment_needs_review(0.95, [0.99, 0.95], 0.0, 0.5) is False

    def test_one_very_bad_word_flags_despite_good_average(self):
        # Average is fine, but one word at 0.1 means the sentence may be wrong.
        assert segment_needs_review(0.9, [0.99, 0.99, 0.1], 0.0, 0.5) is True

    def test_silence_suspicion_flags(self):
        assert segment_needs_review(0.99, [0.99], 0.9, 0.5) is True

    def test_no_words_falls_back_to_average(self):
        assert segment_needs_review(0.9, [], 0.0, 0.5) is False
        assert segment_needs_review(0.2, [], 0.0, 0.5) is True

    def test_thresholds_are_sane(self):
        assert 0 < WORD_MIN_THRESHOLD < WORD_LOW_THRESHOLD < 1
