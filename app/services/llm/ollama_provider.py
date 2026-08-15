import json
import re
import time

import httpx

from app.config import config
from app.services.llm import prompts
from app.services.llm.base import (
    SOCIAL_PLATFORMS,
    ChapterCandidate,
    DescriptionAndKeywords,
    ScriptResult,
    SeoSuggestion,
    SocialGroup,
    SoundbiteCandidate,
    TitleCandidate,
)

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


class OllamaProvider:
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

    def generate_titles(self, transcript_text: str) -> list[TitleCandidate]:
        system, user, schema = prompts.titles_prompt(transcript_text, self.custom_instructions)
        data = self._call(system, user, schema)
        return [TitleCandidate(text=t["text"], score=int(t["score"])) for t in data["titles"]]

    def generate_description_and_keywords(self, transcript_text: str) -> DescriptionAndKeywords:
        system, user, schema = prompts.description_prompt(transcript_text, self.custom_instructions)
        data = self._call(system, user, schema)
        return DescriptionAndKeywords(description=data["description"], keywords=data["keywords"])

    def generate_social_posts(self, transcript_text: str, description: str, tone: str = "casual") -> list[SocialGroup]:
        system, user, schema = prompts.social_posts_prompt(transcript_text, description, tone, self.custom_instructions)
        data = self._call(system, user, schema)
        key_map = {"X": "x_posts", "Instagram": "instagram_posts", "Threads": "threads_posts"}
        return [
            SocialGroup(platform=name, initial=initial, color=color, posts=data[key_map[name]])
            for name, initial, color in SOCIAL_PLATFORMS
        ]

    def select_soundbites(self, transcript_text: str) -> list[SoundbiteCandidate]:
        system, user, schema = prompts.soundbites_prompt(transcript_text, self.custom_instructions)
        data = self._call(system, user, schema)
        return [SoundbiteCandidate(quote=s["quote"]) for s in data["soundbites"]]

    def generate_chapters(self, transcript_text: str) -> list[ChapterCandidate]:
        system, user, schema = prompts.chapters_prompt(transcript_text, self.custom_instructions)
        data = self._call(system, user, schema)
        return [ChapterCandidate(title=c["title"], start_quote=c["start_quote"]) for c in data["chapters"]]

    def generate_seo_suggestion(
        self, title: str, description: str, transcript_text: str | None = None
    ) -> SeoSuggestion:
        system, user, schema = prompts.seo_suggestion_prompt(
            title, description, self.custom_instructions, transcript_text
        )
        data = self._call(system, user, schema)
        return SeoSuggestion(title=data["title"], description=data["description"], keywords=data["keywords"])

    def generate_script(
        self, topic: str, research: str, style_excerpts: str, custom_instructions: str = ""
    ) -> ScriptResult:
        system, user, schema = prompts.script_prompt(topic, research, style_excerpts, custom_instructions)
        data = self._call(system, user, schema)
        return ScriptResult(outline=data["outline"], script=data["script"])
