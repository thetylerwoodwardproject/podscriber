import json

from app.models import Chapter


def build_chapters_json(chapters: list[Chapter]) -> str:
    """Podcasting 2.0 JSON Chapters format — https://github.com/Podcastindex-org/podcast-namespace/blob/main/chapters/jsonChapters.md"""
    payload = {
        "version": "1.2.0",
        "chapters": [{"startTime": round(c.start_ms / 1000, 3), "title": c.title} for c in chapters],
    }
    return json.dumps(payload, indent=2) + "\n"
