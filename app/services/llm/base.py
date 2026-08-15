from dataclasses import dataclass, field
from typing import Protocol

from app.services.llm import prompts


@dataclass
class TitleCandidate:
    text: str
    score: int


@dataclass
class SocialGroup:
    platform: str
    initial: str
    color: str
    posts: list[str] = field(default_factory=list)


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


SEO_TITLE_MAX_CHARS = 60


def _clamp_title(title: str, max_chars: int = SEO_TITLE_MAX_CHARS) -> str:
    """Enforces the podcast-app title-truncation limit even if a model ignores the prompt's
    character-count instruction (smaller local models especially aren't reliable about it)."""
    title = title.strip()
    if len(title) <= max_chars:
        return title
    truncated = title[:max_chars]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(" -–—,;:")


@dataclass
class ScriptResult:
    outline: list[str]
    script: str


@dataclass
class SeoSuggestion:
    title: str
    description: str
    keywords: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.title = _clamp_title(self.title)


SOCIAL_PLATFORMS = [
    ("X", "X", "#111111"),
    ("Instagram", "IG", "#c2185b"),
    ("Threads", "T", "#3a352c"),
]


class LLMProvider(Protocol):
    def generate_titles(self, transcript_text: str) -> list[TitleCandidate]: ...
    def generate_description_and_keywords(self, transcript_text: str) -> DescriptionAndKeywords: ...
    def generate_social_posts(self, transcript_text: str, description: str, tone: str = "casual") -> list[SocialGroup]: ...
    def select_soundbites(self, transcript_text: str) -> list[SoundbiteCandidate]: ...
    def generate_chapters(self, transcript_text: str) -> list[ChapterCandidate]: ...
    def generate_seo_suggestion(
        self, title: str, description: str, transcript_text: str | None = None
    ) -> SeoSuggestion: ...
    def generate_script(
        self, topic: str, research: str, style_excerpts: str, custom_instructions: str = ""
    ) -> ScriptResult: ...


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
