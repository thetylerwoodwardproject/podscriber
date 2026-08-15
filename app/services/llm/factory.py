from sqlalchemy.orm import Session

from app.services import settings_store
from app.services.llm.base import LLMProvider


def _parse_positive_int(raw: str) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


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
    num_ctx = _parse_positive_int(settings_store.get(db, "ollama_num_ctx"))
    keep_alive = settings_store.get(db, "ollama_keep_alive") or None
    return OllamaProvider(
        model=model, custom_instructions=custom_instructions, num_ctx=num_ctx, keep_alive=keep_alive
    )
