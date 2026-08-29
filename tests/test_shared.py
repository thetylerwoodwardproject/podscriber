from datetime import UTC, datetime, timedelta

from app.models import SocialPublish
from app.routers._shared import sanitize_download_filename, social_publish_status_label


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


def test_social_publish_status_label_none_row():
    assert social_publish_status_label(None) == ""


def test_social_publish_status_label_error():
    pub = SocialPublish(platform="x", status="error", error_message="No connected integration.")
    assert social_publish_status_label(pub) == "Failed: No connected integration."


def test_social_publish_status_label_error_without_message():
    pub = SocialPublish(platform="x", status="error", error_message=None)
    assert social_publish_status_label(pub) == "Failed"


def test_social_publish_status_label_done_no_scheduled_at():
    pub = SocialPublish(platform="x", status="done", scheduled_at=None)
    assert social_publish_status_label(pub) == "Posted"


def test_social_publish_status_label_done_future_scheduled_at_reads_scheduled():
    future = datetime.now(UTC) + timedelta(days=1)
    pub = SocialPublish(platform="x", status="done", scheduled_at=future)
    label = social_publish_status_label(pub)
    assert label.startswith("Scheduled for ")


def test_social_publish_status_label_done_past_scheduled_at_reads_posted():
    past = datetime.now(UTC) - timedelta(days=1)
    pub = SocialPublish(platform="x", status="done", scheduled_at=past)
    label = social_publish_status_label(pub)
    assert label.startswith("Posted ")


def test_social_publish_status_label_handles_naive_datetime():
    # SQLite round-trips DateTime columns as naive — mirror that here rather than assuming
    # scheduled_at always carries tzinfo like it does immediately after construction.
    naive_future = (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None)
    pub = SocialPublish(platform="x", status="done", scheduled_at=naive_future)
    assert social_publish_status_label(pub).startswith("Scheduled for ")
