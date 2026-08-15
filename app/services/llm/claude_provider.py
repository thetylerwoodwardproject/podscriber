import json

from app.services.llm.base import BaseLLMProvider


class ClaudeProvider(BaseLLMProvider):
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
