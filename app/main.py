import logging
import shutil

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import config
from app.db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("podscriber")

app = FastAPI(title="Podscriber")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    if shutil.which("ffmpeg") is None:
        logger.warning(
            "ffmpeg was not found on PATH. Audio clipping, VTT-adjacent duration "
            "detection, and video export will fail until you run: sudo apt install ffmpeg"
        )


app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/media", StaticFiles(directory=str(config.media_dir)), name="media")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ffmpeg": shutil.which("ffmpeg") is not None}


from app.routers import (  # noqa: E402
    analytics,
    generator,
    improvements,
    library,
    processing,
    results,
    settings,
    upload,
    video_clip,
)

app.include_router(library.router)
app.include_router(upload.router)
app.include_router(processing.router)
app.include_router(results.router)
app.include_router(video_clip.router)
app.include_router(settings.router)
app.include_router(analytics.router)
app.include_router(improvements.router)
app.include_router(generator.router)
