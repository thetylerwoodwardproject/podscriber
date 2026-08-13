from app.routers._shared import sanitize_download_filename


def test_sanitize_download_filename_plain_name():
    assert sanitize_download_filename("my clip", "fallback") == "my clip.mp4"


def test_sanitize_download_filename_strips_existing_mp4_extension():
    assert sanitize_download_filename("my clip.mp4", "fallback") == "my clip.mp4"
    assert sanitize_download_filename("my clip.MP4", "fallback") == "my clip.mp4"


def test_sanitize_download_filename_strips_unsafe_characters():
    assert sanitize_download_filename("a/b\\c:d*e?f\"g<h>i|j", "fallback") == "abcdefghij.mp4"


def test_sanitize_download_filename_collapses_whitespace_and_trims():
    assert sanitize_download_filename("  my   clip   ", "fallback") == "my clip.mp4"


def test_sanitize_download_filename_falls_back_when_empty_or_none():
    assert sanitize_download_filename("", "fallback") == "fallback.mp4"
    assert sanitize_download_filename(None, "fallback") == "fallback.mp4"
    assert sanitize_download_filename("   ", "fallback") == "fallback.mp4"


def test_sanitize_download_filename_caps_length():
    long_name = "a" * 200
    result = sanitize_download_filename(long_name, "fallback")
    assert result == "a" * 80 + ".mp4"
