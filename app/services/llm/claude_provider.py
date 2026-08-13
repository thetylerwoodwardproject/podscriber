import json

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


class ClaudeProvider:
    def __init__(self, api_key: str, model: str = "claude-sonnet-5", custom_instructions: str = ""):
        self.api_key = api_key
        self.model = model
        self.custom_instructions = custom_instructions

    def _client(self):
        import anthropic

        return anthropic.Anthropic(api_key=self.api_key)

    def _call(self, system: str, user: str, schema: dict) -> dict:
        client = self._client()
        response = client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)

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
