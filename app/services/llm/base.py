from dataclasses import dataclass, field
from typing import Protocol

from app.services.llm import prompts


@dataclass
class TitleCandidate:
    text: str
    score: int


SOCIAL_POST_MAX_CHARS = 280
SOCIAL_POST_MAX_HASHTAGS = 4


def _normalize_hashtags(tags: list[str]) -> list[str]:
    """Strips whitespace, drops empties, ensures a leading '#', and caps at
    `SOCIAL_POST_MAX_HASHTAGS` — a model can return too many, or omit the '#', so this is
    enforced in code rather than trusted from the prompt."""
    normalized = []
    for tag in tags:
        tag = tag.strip().replace(" ", "")
        if not tag.lstrip("#"):
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        normalized.append(tag)
    return normalized[:SOCIAL_POST_MAX_HASHTAGS]


@dataclass
class SocialPost:
    text: str
    hashtags: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.text = _clamp_text(self.text, max_chars=SOCIAL_POST_MAX_CHARS)
        self.hashtags = _normalize_hashtags(self.hashtags)


@dataclass
class DescriptionAndKeywords:
    description: str
    keywords: list[str]


@dataclass
class SoundbiteCandidate:
    quote: str


@dataclass
class ChapterCandidate:
    title: str
    start_quote: str


@dataclass
class ClipSocial:
    social_post: str
    youtube_title: str

    def __post_init__(self):
        self.social_post = _clamp_text(self.social_post, max_chars=SOCIAL_POST_MAX_CHARS)
        self.youtube_title = _clamp_text(self.youtube_title, max_chars=99)
        if not self.social_post.strip() or not self.youtube_title.strip():
            # A model can return a schema-valid but empty response under load (seen with a
            # large local Ollama model taking several minutes and coming back blank) — treat
            # that as a failure rather than silently saving nothing and reporting success.
            raise ValueError("Model returned an empty social post or YouTube title.")


SEO_TITLE_MAX_CHARS = 60


def _clamp_text(text: str, max_chars: int = SEO_TITLE_MAX_CHARS) -> str:
    """Enforces a length limit even if a model ignores the prompt's character-count
    instruction (smaller local models especially aren't reliable about it)."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(" -–—,;:")


@dataclass
class SeoSuggestion:
    title: str
    description: str
    keywords: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.title = _clamp_text(self.title)


class LLMProvider(Protocol):
    def generate_titles(self, transcript_text: str) -> list[TitleCandidate]: ...
    def generate_description_and_keywords(self, transcript_text: str) -> DescriptionAndKeywords: ...
    def generate_social_posts(self, transcript_text: str, description: str, tone: str = "casual") -> list[SocialPost]: ...
    def select_soundbites(self, transcript_text: str) -> list[SoundbiteCandidate]: ...
    def generate_clip_social(self, quote: str, episode_title: str) -> ClipSocial: ...
    def generate_chapters(self, transcript_text: str) -> list[ChapterCandidate]: ...
    def generate_seo_suggestion(
        self, title: str, description: str, transcript_text: str | None = None
    ) -> SeoSuggestion: ...


class BaseLLMProvider:
    """Implements the `LLMProvider` prompt-building/response-parsing methods shared by every
    provider. Subclasses only need to set `self.custom_instructions` and implement
    `_call(system, user, schema) -> dict`."""

    custom_instructions: str

    def _call(self, system: str, user: str, schema: dict) -> dict:
        raise NotImplementedError

    def generate_titles(self, transcript_text: str) -> list[TitleCandidate]:
        system, user, schema = prompts.titles_prompt(transcript_text, self.custom_instructions)
        data = self._call(system, user, schema)
        return [TitleCandidate(text=t["text"], score=int(t["score"])) for t in data["titles"]]

    def generate_description_and_keywords(self, transcript_text: str) -> DescriptionAndKeywords:
        system, user, schema = prompts.description_prompt(transcript_text, self.custom_instructions)
        data = self._call(system, user, schema)
        return DescriptionAndKeywords(description=data["description"], keywords=data["keywords"])

    def generate_social_posts(self, transcript_text: str, description: str, tone: str = "casual") -> list[SocialPost]:
        system, user, schema = prompts.social_posts_prompt(transcript_text, description, tone, self.custom_instructions)
        data = self._call(system, user, schema)
        # The schema can't enforce "exactly 3" (Claude's structured-output API rejects array
        # minItems/maxItems other than 0 or 1), so cap defensively here in case a model returns
        # more than asked for.
        return [SocialPost(text=p["text"], hashtags=p.get("hashtags", [])) for p in data["posts"][:3]]

    def select_soundbites(self, transcript_text: str) -> list[SoundbiteCandidate]:
        system, user, schema = prompts.soundbites_prompt(transcript_text, self.custom_instructions)
        data = self._call(system, user, schema)
        return [SoundbiteCandidate(quote=s["quote"]) for s in data["soundbites"]]

    def generate_clip_social(self, quote: str, episode_title: str) -> ClipSocial:
        system, user, schema = prompts.clip_social_prompt(quote, episode_title, self.custom_instructions)
        data = self._call(system, user, schema)
        return ClipSocial(social_post=data["social_post"], youtube_title=data["youtube_title"])

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
