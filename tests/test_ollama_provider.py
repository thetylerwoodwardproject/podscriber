from unittest.mock import MagicMock, patch

from app.services.llm.ollama_provider import OllamaProvider


def _mock_response(content: str = "{}"):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"message": {"content": content}}
    return resp


def test_keep_alive_sent_as_number_when_unitless():
    provider = OllamaProvider(model="qwen3:4b-instruct", keep_alive="-1")
    with patch("app.services.llm.ollama_provider.httpx.post", return_value=_mock_response()) as mock_post:
        provider._call("system", "user", {})
    assert mock_post.call_args.kwargs["json"]["keep_alive"] == -1


def test_keep_alive_sent_as_string_when_it_has_a_unit():
    provider = OllamaProvider(model="qwen3:4b-instruct", keep_alive="30m")
    with patch("app.services.llm.ollama_provider.httpx.post", return_value=_mock_response()) as mock_post:
        provider._call("system", "user", {})
    assert mock_post.call_args.kwargs["json"]["keep_alive"] == "30m"


def test_keep_alive_omitted_when_blank():
    provider = OllamaProvider(model="qwen3:4b-instruct", keep_alive="")
    with patch("app.services.llm.ollama_provider.httpx.post", return_value=_mock_response()) as mock_post:
        provider._call("system", "user", {})
    assert "keep_alive" not in mock_post.call_args.kwargs["json"]
