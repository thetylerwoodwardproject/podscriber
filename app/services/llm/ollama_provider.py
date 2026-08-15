import json
import re
import time

import httpx

from app.config import config
from app.services.llm.base import BaseLLMProvider

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json(text: str) -> dict:
    text = _THINK_TAG_RE.sub("", text).strip()
    fence_match = _CODE_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"Could not parse JSON from Ollama response: {text[:200]!r}")


def list_models(base_url: str | None = None) -> list[str] | None:
    try:
        resp = httpx.get(f"{base_url or config.ollama_base_url}/api/tags", timeout=1.5)
        resp.raise_for_status()
        return sorted(m["name"] for m in resp.json().get("models", []))
    except httpx.HTTPError:
        return None


class OllamaProvider(BaseLLMProvider):
    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        custom_instructions: str = "",
        num_ctx: int | None = None,
        keep_alive: str | None = None,
    ):
        self.model = model
        self.base_url = base_url or config.ollama_base_url
        self.custom_instructions = custom_instructions
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive

    def _call(self, system: str, user: str, schema: dict) -> dict:
        # Local CPU inference of larger structured outputs (e.g. 12 social posts) can run
        # well past a couple of minutes, especially with a reasoning model's <think> pass.
        # This runs inside a background job thread, not a request/response cycle, so a long
        # timeout just means slower progress rather than a blocked page.
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,
            "stream": False,
        }
        if self.num_ctx:
            payload["options"] = {"num_ctx": self.num_ctx}
        if self.keep_alive:
            # Ollama's Go duration parser only accepts unit-less values (e.g. "-1", "0") as a
            # JSON number — as a JSON string it requires a unit suffix ("30m", "1h") and 400s
            # on a bare "-1"/"0". Send plain integers as numbers; pass anything else (duration
            # strings with units) through unchanged.
            try:
                payload["keep_alive"] = int(self.keep_alive)
            except ValueError:
                payload["keep_alive"] = self.keep_alive
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=900.0)
        except httpx.TimeoutException:
            # A single retry gives a transient stall (rather than sustained CPU contention
            # from another job) a second chance without doubling every call's worst case.
            time.sleep(5.0)
            try:
                resp = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=900.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    "Ollama did not respond within 15 minutes. It's likely busy running "
                    "another job on this machine — wait for other jobs to finish and try again."
                ) from exc
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return _extract_json(content)
