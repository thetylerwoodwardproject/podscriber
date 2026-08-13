from sqlalchemy.orm import Session

from app.models import SettingsKV

DEFAULTS = {
    "claude_api_key": "",
    "claude_model": "claude-sonnet-5",
    "openai_api_key": "",
    "openai_model": "gpt-5-mini",
    "openai_share_key": "false",  # if "true", text generation uses whisper_api_key instead
    "whisper_api_key": "",
    "podcast_index_api_key": "",
    "podcast_index_api_secret": "",
    "podcast_feed_url": "",
    "podcast_index_feed_id": "",
    "podcast_guid": "",
    "op3_api_key": "",
    "op3_show_uuid": "",  # resolved via OP3's /shows lookup, cleared whenever podcast_feed_url changes
    "text_provider": "ollama",  # claude|ollama|openai
    "ollama_model": "qwen3:4b-instruct",
    "transcription_provider": "local",  # local|openai
    "local_whisper_model_size": "small",
    "custom_instructions": "",  # applied to every AI generation step: titles, description, social, soundbites, chapters
    "generator_custom_instructions": "",  # applied to every Generator script — separate from custom_instructions above
}


def get_all(db: Session) -> dict:
    rows = {row.key: row.value for row in db.query(SettingsKV).all()}
    return {**DEFAULTS, **rows}


def get(db: Session, key: str) -> str:
    row = db.get(SettingsKV, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key, "")


def set_many(db: Session, values: dict[str, str]) -> None:
    for key, value in values.items():
        row = db.get(SettingsKV, key)
        if row is None:
            row = SettingsKV(key=key, value=value)
            db.add(row)
        else:
            row.value = value
    db.commit()
