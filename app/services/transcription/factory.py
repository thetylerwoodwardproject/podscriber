from sqlalchemy.orm import Session

from app.services import settings_store
from app.services.transcription.base import TranscriptionProvider


def get_transcription_provider(db: Session) -> TranscriptionProvider:
    provider = settings_store.get(db, "transcription_provider")
    if provider == "openai":
        from app.services.transcription.openai_whisper import OpenAIWhisperProvider

        api_key = settings_store.get(db, "whisper_api_key")
        if not api_key:
            raise RuntimeError("OpenAI Whisper API key is not set. Add it in Settings.")
        return OpenAIWhisperProvider(api_key=api_key)

    from app.services.transcription.local_whisper import LocalWhisperProvider

    model_size = settings_store.get(db, "local_whisper_model_size") or "small"
    return LocalWhisperProvider(model_size=model_size)
