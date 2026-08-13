from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Episode


def style_excerpts(db: Session, max_episodes: int = 8, chars_per_episode: int = 800) -> str:
    """Pulls a short excerpt from each of the show's most recent processed episodes to use as a
    style reference. This is plain retrieval, re-run fresh on every generation — as more episodes
    get uploaded, later generations draw on a larger/more recent pool without any separate
    training or indexing step."""
    episodes = (
        db.execute(
            select(Episode)
            .where(Episode.status == "processed")
            .order_by(Episode.created_at.desc())
            .limit(max_episodes)
        )
        .scalars()
        .all()
    )
    blocks = []
    for ep in episodes:
        if ep.transcript is None or not ep.transcript.full_text:
            continue
        excerpt = ep.transcript.full_text[:chars_per_episode]
        blocks.append(f"From \"{ep.title or ep.original_filename}\":\n{excerpt}")
    return "\n\n".join(blocks)
