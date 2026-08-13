from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PODSCRIBER_")

    db_path: Path = BASE_DIR / "podscriber.db"
    media_dir: Path = BASE_DIR / "media"
    host: str = "127.0.0.1"
    port: int = 8000
    max_upload_bytes: int = 500 * 1024 * 1024  # 500MB, matches the mockup's stated limit
    ollama_base_url: str = "http://localhost:11434"

    @property
    def uploads_dir(self) -> Path:
        return self.media_dir / "uploads"


config = Config()
config.uploads_dir.mkdir(parents=True, exist_ok=True)
