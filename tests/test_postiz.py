from unittest.mock import MagicMock, patch

import pytest

from app.services.postiz import Integration, PostizError, create_post, list_integrations, upload_media


def _mock_response(status_code: int, *, json_data=None, text: str = "", headers: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = text
    resp.headers = headers or {}
    return resp


def test_list_integrations_success():
    # Postiz's real response uses "identifier" for the platform slug, not "platform"/"provider" —
    # see docs.postiz.com/public-api/integrations/list.
    resp = _mock_response(200, json_data=[{"id": 1, "identifier": "tiktok", "name": "My TikTok"}])
    with patch("app.services.postiz.httpx.get", return_value=resp):
        result = list_integrations("https://postiz.example.com/api", "key")
    assert result == [Integration(id="1", platform="tiktok", name="My TikTok")]


def test_list_integrations_redirect_gives_helpful_error():
    resp = _mock_response(307, text="/auth", headers={"location": "/auth"})
    with patch("app.services.postiz.httpx.get", return_value=resp):
        with pytest.raises(PostizError) as exc_info:
            list_integrations("https://postiz.example.com", "key")
    message = str(exc_info.value)
    assert "redirected" in message
    assert "frontend" in message
    assert "HTTP 307 to /auth" in message


def test_list_integrations_other_failure_uses_generic_message():
    resp = _mock_response(401, text="Unauthorized")
    with patch("app.services.postiz.httpx.get", return_value=resp):
        with pytest.raises(PostizError) as exc_info:
            list_integrations("https://postiz.example.com/api", "key")
    assert "Postiz returned HTTP 401: Unauthorized" in str(exc_info.value)


def test_upload_media_infers_content_type_from_extension(tmp_path):
    resp = _mock_response(200, json_data={"id": "m1", "path": "x"})
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video")
    image_path = tmp_path / "pic.jpg"
    image_path.write_bytes(b"fake image")

    with patch("app.services.postiz.httpx.post", return_value=resp) as mock_post:
        upload_media("https://postiz.example.com/api", "key", str(video_path))
        assert mock_post.call_args.kwargs["files"]["file"][2] == "video/mp4"

        upload_media("https://postiz.example.com/api", "key", str(image_path))
        assert mock_post.call_args.kwargs["files"]["file"][2] == "image/jpeg"


def test_upload_media_explicit_content_type_overrides_guess(tmp_path):
    resp = _mock_response(200, json_data={"id": "m1", "path": "x"})
    path = tmp_path / "file.bin"
    path.write_bytes(b"data")

    with patch("app.services.postiz.httpx.post", return_value=resp) as mock_post:
        upload_media("https://postiz.example.com/api", "key", str(path), content_type="application/pdf")
    assert mock_post.call_args.kwargs["files"]["file"][2] == "application/pdf"


def test_create_post_media_list_becomes_image_field():
    resp = _mock_response(200, json_data=[{"postId": "p1"}])
    with patch("app.services.postiz.httpx.post", return_value=resp) as mock_post:
        create_post(
            "https://postiz.example.com/api",
            "key",
            integration_id="int-1",
            platform="instagram",
            content="hello",
            media=[{"id": "a"}, {"id": "b"}],
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
        )
    payload = mock_post.call_args.kwargs["json"]
    assert payload["posts"][0]["value"][0]["image"] == [{"id": "a"}, {"id": "b"}]


def test_create_post_media_none_gives_empty_image_list():
    resp = _mock_response(200, json_data=[{"postId": "p1"}])
    with patch("app.services.postiz.httpx.post", return_value=resp) as mock_post:
        create_post(
            "https://postiz.example.com/api",
            "key",
            integration_id="int-1",
            platform="x",
            content="hello",
            media=None,
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
        )
    payload = mock_post.call_args.kwargs["json"]
    assert payload["posts"][0]["value"][0]["image"] == []


def test_create_post_settings_merge_under_type():
    resp = _mock_response(200, json_data=[{"postId": "p1"}])
    with patch("app.services.postiz.httpx.post", return_value=resp) as mock_post:
        create_post(
            "https://postiz.example.com/api",
            "key",
            integration_id="int-1",
            platform="youtube",
            content="hello",
            media=None,
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
            settings={"title": "My Video", "type": "public"},
        )
    payload = mock_post.call_args.kwargs["json"]
    assert payload["posts"][0]["settings"] == {"__type": "youtube", "title": "My Video", "type": "public"}


def test_create_post_settings_omitted_keeps_bare_type():
    resp = _mock_response(200, json_data=[{"postId": "p1"}])
    with patch("app.services.postiz.httpx.post", return_value=resp) as mock_post:
        create_post(
            "https://postiz.example.com/api",
            "key",
            integration_id="int-1",
            platform="x",
            content="hello",
            media=None,
            post_type="now",
            date="2026-08-20T00:00:00.000Z",
        )
    payload = mock_post.call_args.kwargs["json"]
    assert payload["posts"][0]["settings"] == {"__type": "x"}
