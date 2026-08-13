import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.services import settings_store
from app.services.llm.factory import get_llm_provider
from app.services.llm.ollama_provider import OllamaProvider


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_claude_provider_requires_api_key(db):
    settings_store.set_many(db, {"text_provider": "claude"})
    with pytest.raises(RuntimeError):
        get_llm_provider(db)


def test_claude_provider_constructed_with_api_key(db):
    settings_store.set_many(db, {"text_provider": "claude", "claude_api_key": "sk-ant-test"})
    provider = get_llm_provider(db)
    assert provider.api_key == "sk-ant-test"
    assert provider.model == "claude-sonnet-5"


def test_openai_provider_requires_api_key(db):
    settings_store.set_many(db, {"text_provider": "openai"})
    with pytest.raises(RuntimeError):
        get_llm_provider(db)


def test_openai_provider_constructed_with_api_key(db):
    settings_store.set_many(db, {"text_provider": "openai", "openai_api_key": "sk-test", "openai_model": "gpt-5"})
    provider = get_llm_provider(db)
    assert provider.api_key == "sk-test"
    assert provider.model == "gpt-5"


def test_unknown_provider_falls_back_to_ollama(db):
    settings_store.set_many(db, {"text_provider": "not-a-real-provider"})
    provider = get_llm_provider(db)
    assert isinstance(provider, OllamaProvider)


def test_default_provider_is_ollama(db):
    provider = get_llm_provider(db)
    assert isinstance(provider, OllamaProvider)


def test_custom_instructions_passed_to_provider(db):
    settings_store.set_many(db, {"custom_instructions": "Always mention the guest's name."})
    provider = get_llm_provider(db)
    assert provider.custom_instructions == "Always mention the guest's name."
