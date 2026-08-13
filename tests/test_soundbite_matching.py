from app.models import TranscriptSegment
from app.services.soundbite_matching import match_quote_to_timestamps, quote_coverage


def _seg(index, start_ms, end_ms, text, words=None):
    return TranscriptSegment(index=index, start_ms=start_ms, end_ms=end_ms, text=text, words=words)


def _word_segments():
    # "A recipe is just someone else's guess" (0-4000ms) + "The only measurement that matters is salt" (4000-9000ms)
    seg1_words = [
        {"word": w, "start_ms": 0 + i * 500, "end_ms": 500 + i * 500}
        for i, w in enumerate(["A", "recipe", "is", "just", "someone", "elses", "guess"])
    ]
    seg2_words = [
        {"word": w, "start_ms": 4000 + i * 700, "end_ms": 4700 + i * 700}
        for i, w in enumerate(["The", "only", "measurement", "that", "matters", "is", "salt"])
    ]
    return [
        _seg(0, 0, 3500, "A recipe is just someone elses guess", words=seg1_words),
        _seg(1, 4000, 8900, "The only measurement that matters is salt", words=seg2_words),
    ]


def test_exact_quote_maps_to_correct_word_span():
    segments = _word_segments()
    start_ms, end_ms = match_quote_to_timestamps(segments, "someone elses guess")
    # "someone" starts at word index 4 -> 2000ms; "guess" ends at word index 6 -> 3500ms
    assert start_ms == 2000
    assert end_ms == 3500


def test_quote_in_second_segment():
    segments = _word_segments()
    start_ms, end_ms = match_quote_to_timestamps(segments, "matters is salt")
    assert start_ms >= 4000
    assert end_ms <= 8900


def test_no_reasonable_match_falls_back_without_crashing():
    segments = _word_segments()
    start_ms, end_ms = match_quote_to_timestamps(segments, "completely unrelated text that never appears anywhere")
    assert isinstance(start_ms, int)
    assert isinstance(end_ms, int)
    assert start_ms <= end_ms


def test_empty_segments_returns_zero():
    assert match_quote_to_timestamps([], "anything") == (0, 0)


def test_quote_coverage_high_for_verbatim_quote():
    segments = _word_segments()
    assert quote_coverage(segments, "someone elses guess") > 0.9


def test_quote_coverage_low_for_degenerate_llm_output():
    segments = _word_segments()
    garbage = (
        "Wait this is broken, ignore.\"}]}Let me redo this properly without breaking JSON.{'\"'\"''"
    )
    assert quote_coverage(segments, garbage) < 0.5


def test_quote_coverage_zero_for_empty_quote_or_segments():
    segments = _word_segments()
    assert quote_coverage(segments, "") == 0.0
    assert quote_coverage([], "anything") == 0.0


def test_segment_without_word_timestamps_falls_back_to_segment_span():
    segments = [_seg(0, 1000, 5000, "hello there world", words=None)]
    start_ms, end_ms = match_quote_to_timestamps(segments, "hello there world")
    assert start_ms == 1000
    assert end_ms == 5000
