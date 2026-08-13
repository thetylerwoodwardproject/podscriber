from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Episode
from app.routers._shared import recent_episodes
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def library(request: Request, db: Session = Depends(get_db)):
    episodes = list(
        db.execute(
            select(Episode).where(Episode.source == "upload").order_by(Episode.created_at.desc())
        ).scalars()
    )
    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "active_nav": "library",
            "episodes": episodes,
            "recent_episodes": recent_episodes(db),
        },
    )
