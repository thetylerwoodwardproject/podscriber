import os

from fastapi.templating import Jinja2Templates

from app.routers._shared import format_duration, ms_to_clock, status_label

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["duration"] = format_duration
templates.env.filters["status_label"] = status_label
templates.env.filters["clock"] = ms_to_clock


def asset_url(path: str) -> str:
    """Static asset URL with a mtime-based cache-busting query param."""
    try:
        version = int(os.path.getmtime(os.path.join("app/static", path)))
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


templates.env.globals["asset_url"] = asset_url
