from dataclasses import dataclass, field
from typing import Protocol


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
