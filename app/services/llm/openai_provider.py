import json

from app.services.llm.base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-5-mini", custom_instructions: str = ""):
        self.api_key = api_key
        self.model = model
        self.custom_instructions = custom_instructions

    def _client(self):
        from openai import OpenAI

        return OpenAI(api_key=self.api_key)

    def _call(self, system: str, user: str, schema: dict) -> dict:
        client = self._client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "podscriber_output", "schema": schema, "strict": True},
            },
        )
        return json.loads(response.choices[0].message.content)
