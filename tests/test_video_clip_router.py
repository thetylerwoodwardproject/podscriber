from app.routers import video_clip as video_clip_router


def _make_episode_with_soundbite(db):
    from app.models import Episode, Soundbite

    episode = Episode(title="Ep", original_filename="ep.mp3", file_path="/tmp/ep.mp3", status="processed")
    db.add(episode)
    db.commit()
    db.refresh(episode)
    sb = Soundbite(episode_id=episode.id, quote="a great quote", start_ms=0, end_ms=1000)
    db.add(sb)
    db.commit()
    db.refresh(sb)
    return episode, sb


def _make_clip(db, soundbite_id, **kwargs):
    from app.models import VideoClip

    clip = VideoClip(soundbite_id=soundbite_id, **kwargs)
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


def test_duplicate_clip_copies_settings_but_not_export(db):
    episode, sb = _make_episode_with_soundbite(db)
    clip = _make_clip(
        db,
        sb.id,
        background_image_path="/media/bg.png",
        brightness=1.3,
        waveform_color="#0f8a6c",
        social_post="check this out",
        youtube_title="Great clip",
        exported_video_path="/media/clip.mp4",
    )

    result = video_clip_router.duplicate_clip(episode.id, sb.id, clip.id, db)

    assert result["ok"] is True
    assert result["url"] == f"/episodes/{episode.id}/soundbites/{sb.id}/video/{clip.id + 1}"

    db.refresh(sb)
    assert len(sb.video_clips) == 2
    new_clip = sb.video_clips[1]
    assert new_clip.id != clip.id
    assert new_clip.background_image_path == "/media/bg.png"
    assert new_clip.brightness == 1.3
    assert new_clip.waveform_color == "#0f8a6c"
    assert new_clip.social_post == "check this out"
    assert new_clip.youtube_title == "Great clip"
    # The point of duplicating: a fresh, unexported variant that doesn't clobber the original.
    assert new_clip.exported_video_path is None
    assert clip.exported_video_path == "/media/clip.mp4"


def test_duplicate_clip_rejects_mismatched_soundbite(db):
    episode, sb = _make_episode_with_soundbite(db)
    clip = _make_clip(db, sb.id)
    _, other_sb = _make_episode_with_soundbite(db)

    result = video_clip_router.duplicate_clip(episode.id, other_sb.id, clip.id, db)

    assert result == {"ok": False, "error": "Video not found."}


def test_video_editor_entry_creates_and_redirects_to_first_clip(db):
    episode, sb = _make_episode_with_soundbite(db)

    response = video_clip_router.video_editor_entry(episode.id, sb.id, db)

    db.refresh(sb)
    assert len(sb.video_clips) == 1
    assert response.headers["location"] == f"/episodes/{episode.id}/soundbites/{sb.id}/video/{sb.video_clips[0].id}"


def test_video_editor_entry_reuses_earliest_existing_clip(db):
    episode, sb = _make_episode_with_soundbite(db)
    first = _make_clip(db, sb.id)
    _make_clip(db, sb.id)

    response = video_clip_router.video_editor_entry(episode.id, sb.id, db)

    assert response.headers["location"] == f"/episodes/{episode.id}/soundbites/{sb.id}/video/{first.id}"


def test_export_selected_videos_targets_first_clip_per_soundbite(db, monkeypatch):
    import asyncio

    episode, sb = _make_episode_with_soundbite(db)
    first = _make_clip(db, sb.id)
    _make_clip(db, sb.id)
    submitted = []
    monkeypatch.setattr(video_clip_router, "submit_video_export", lambda job_id: submitted.append(job_id))

    class _FakeRequest:
        async def json(self):
            return {"soundbite_ids": [sb.id]}

    result = asyncio.run(video_clip_router.export_selected_videos(episode.id, _FakeRequest(), db))

    assert result["jobs"] == [{"soundbite_id": sb.id, "clip_id": first.id, "job_id": submitted[0]}]
