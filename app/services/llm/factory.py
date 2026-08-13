from sqlalchemy.orm import Session

from app.services import settings_store
from app.services.llm.base import LLMProvider


def get_llm_provider(db: Session) -> LLMProvider:
    provider = settings_store.get(db, "text_provider")
    custom_instructions = settings_store.get(db, "custom_instructions")

    if provider == "claude":
        from app.services.llm.claude_provider import ClaudeProvider

        api_key = settings_store.get(db, "claude_api_key")
        if not api_key:
            raise RuntimeError("Claude API key is not set. Add it in Settings.")
        model = settings_store.get(db, "claude_model") or "claude-sonnet-5"
        return ClaudeProvider(api_key=api_key, model=model, custom_instructions=custom_instructions)

    if provider == "openai":
        from app.services.llm.openai_provider import OpenAIProvider

        api_key = settings_store.get(db, "openai_api_key")
        if not api_key:
            raise RuntimeError("OpenAI API key is not set. Add it in Settings.")
        model = settings_store.get(db, "openai_model") or "gpt-5-mini"
        return OpenAIProvider(api_key=api_key, model=model, custom_instructions=custom_instructions)

    from app.services.llm.ollama_provider import OllamaProvider

    model = settings_store.get(db, "ollama_model") or "qwen3:4b-instruct"
    return OllamaProvider(model=model, custom_instructions=custom_instructions)
