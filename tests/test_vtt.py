from app.models import TranscriptSegment
from app.services.vtt import _format_timestamp, build_vtt


def _seg(start_ms, end_ms, text):
    return TranscriptSegment(index=0, start_ms=start_ms, end_ms=end_ms, text=text)


def test_format_timestamp_zero():
    assert _format_timestamp(0) == "00:00:00.000"


def test_format_timestamp_over_an_hour():
    # 1h 2m 3.456s
    ms = 1 * 3_600_000 + 2 * 60_000 + 3_000 + 456
    assert _format_timestamp(ms) == "01:02:03.456"


def test_format_timestamp_negative_clamped_to_zero():
    assert _format_timestamp(-50) == "00:00:00.000"


def test_build_vtt_header_and_single_cue():
    vtt = build_vtt([_seg(0, 1500, "Hello world")])
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:01.500" in vtt
    assert "Hello world" in vtt


def test_build_vtt_multiple_cues_in_order():
    segs = [_seg(0, 1000, "First"), _seg(1000, 2500, "Second")]
    vtt = build_vtt(segs)
    assert vtt.index("First") < vtt.index("Second")


def test_build_vtt_zero_duration_cue_does_not_crash():
    vtt = build_vtt([_seg(5000, 5000, "Instant")])
    assert "00:00:05.000 --> 00:00:05.001" in vtt
