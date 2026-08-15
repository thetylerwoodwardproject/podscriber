from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers._shared import recent_episodes
from app.services import settings_store
from app.services.llm import ollama_provider
from app.templating import templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    values = settings_store.get_all(db)
    ollama_models = ollama_provider.list_models()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active_nav": "settings",
            "recent_episodes": recent_episodes(db),
            "s": values,
            "ollama_models": ollama_models or [],
            "ollama_reachable": ollama_models is not None,
        },
    )


@router.post("/settings")
def save_settings(
    claude_api_key: str = Form(""),
    claude_model: str = Form("claude-sonnet-5"),
    openai_api_key: str = Form(""),
    openai_model: str = Form("gpt-5-mini"),
    openai_share_key: str = Form(""),
    whisper_api_key: str = Form(""),
    podcast_index_api_key: str = Form(""),
    podcast_index_api_secret: str = Form(""),
    podcast_feed_url: str = Form(""),
    op3_api_key: str = Form(""),
    text_provider: str = Form("ollama"),
    ollama_model: str = Form("qwen3:4b-instruct"),
    ollama_num_ctx: str = Form(""),
    ollama_keep_alive: str = Form(""),
    transcription_provider: str = Form("local"),
    local_whisper_model_size: str = Form("small"),
    custom_instructions: str = Form(""),
    generator_custom_instructions: str = Form(""),
    db: Session = Depends(get_db),
):
    # "Also use this key for text generation" (Transcription card) forces text generation
    # onto OpenAI using the same key, regardless of which text_provider radio was submitted,
    # so the persisted settings stay consistent even without the greying-out JS running.
    shared = bool(openai_share_key)
    if shared:
        text_provider = "openai"
        openai_api_key = whisper_api_key

    podcast_feed_url = podcast_feed_url.strip()
    new_values = {
        "claude_api_key": claude_api_key.strip(),
        "claude_model": claude_model,
        "openai_api_key": openai_api_key.strip(),
        "openai_model": openai_model,
        "openai_share_key": "true" if shared else "false",
        "whisper_api_key": whisper_api_key.strip(),
        "podcast_index_api_key": podcast_index_api_key.strip(),
        "podcast_index_api_secret": podcast_index_api_secret.strip(),
        "podcast_feed_url": podcast_feed_url,
        "op3_api_key": op3_api_key.strip(),
        "text_provider": text_provider,
        "ollama_model": ollama_model.strip(),
        "ollama_num_ctx": ollama_num_ctx.strip(),
        "ollama_keep_alive": ollama_keep_alive.strip(),
        "transcription_provider": transcription_provider,
        "local_whisper_model_size": local_whisper_model_size,
        "custom_instructions": custom_instructions.strip(),
        "generator_custom_instructions": generator_custom_instructions.strip(),
    }
    # A changed feed URL invalidates any feed id/guid/uuid resolved from the old one, so
    # the Stats page doesn't keep querying PodcastIndex/OP3 for the wrong show.
    if podcast_feed_url != settings_store.get(db, "podcast_feed_url"):
        new_values["podcast_index_feed_id"] = ""
        new_values["podcast_guid"] = ""
        new_values["op3_show_uuid"] = ""

    settings_store.set_many(db, new_values)
    return {"ok": True}
