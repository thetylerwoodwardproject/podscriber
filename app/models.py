from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def now_utc() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Episode(TimestampMixin, Base):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, default="")
    original_filename: Mapped[str] = mapped_column(String)
    file_path: Mapped[str] = mapped_column(String)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft|processing|processed|error
    source: Mapped[str] = mapped_column(String, default="upload")  # upload|feed
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="episode", uselist=False, cascade="all, delete-orphan"
    )
    generated_content: Mapped["GeneratedContent | None"] = relationship(
        back_populates="episode", uselist=False, cascade="all, delete-orphan"
    )
    soundbites: Mapped[list["Soundbite"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan", order_by="Soundbite.order_index"
    )
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan", order_by="Chapter.start_ms"
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="episode", cascade="all, delete-orphan")
    video: Mapped["EpisodeVideo | None"] = relationship(
        back_populates="episode", uselist=False, cascade="all, delete-orphan"
    )


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"), nullable=True)
    soundbite_id: Mapped[int | None] = mapped_column(ForeignKey("soundbites.id"), nullable=True)
    generated_script_id: Mapped[int | None] = mapped_column(ForeignKey("generated_scripts.id"), nullable=True)
    job_type: Mapped[str] = mapped_column(String)  # episode_processing|video_export|script_generate
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|running|done|error
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)  # episode_processing: selected STEP_KEYS
    current_step: Mapped[str] = mapped_column(String, default="")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    episode: Mapped["Episode | None"] = relationship(back_populates="jobs")


class Transcript(TimestampMixin, Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), unique=True)
    full_text: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String)  # local_whisper|openai_whisper

    episode: Mapped["Episode"] = relationship(back_populates="transcript")
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan", order_by="TranscriptSegment.index"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"))
    index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    words: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{word,start_ms,end_ms}]

    transcript: Mapped["Transcript"] = relationship(back_populates="segments")


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), unique=True)
    titles: Mapped[list] = mapped_column(JSON, default=list)  # [{text, score}]
    selected_title_index: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)  # [str]
    social_posts: Mapped[list] = mapped_column(JSON, default=list)  # [{platform, initial, color, posts:[str]}]
    llm_provider: Mapped[str] = mapped_column(String, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    episode: Mapped["Episode"] = relationship(back_populates="generated_content")


class Soundbite(Base):
    __tablename__ = "soundbites"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"))
    quote: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    clip_audio_path: Mapped[str | None] = mapped_column(String, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    episode: Mapped["Episode"] = relationship(back_populates="soundbites")
    video_clip: Mapped["VideoClip | None"] = relationship(
        back_populates="soundbite", uselist=False, cascade="all, delete-orphan"
    )


class VideoClip(Base):
    __tablename__ = "video_clips"

    id: Mapped[int] = mapped_column(primary_key=True)
    soundbite_id: Mapped[int] = mapped_column(ForeignKey("soundbites.id"), unique=True)
    background_image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    logo_image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    brightness: Mapped[float] = mapped_column(Float, default=1.0)
    offset_x: Mapped[int] = mapped_column(Integer, default=0)
    offset_y: Mapped[int] = mapped_column(Integer, default=0)
    waveform_offset_y: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str] = mapped_column(Text, default="")
    waveform_color: Mapped[str] = mapped_column(String, default="#e2572c")
    download_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    exported_video_path: Mapped[str | None] = mapped_column(String, nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    soundbite: Mapped["Soundbite"] = relationship(back_populates="video_clip")


class EpisodeVideo(Base):
    __tablename__ = "episode_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), unique=True)
    background_image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    logo_image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    brightness: Mapped[float] = mapped_column(Float, default=1.0)
    waveform_offset_y: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str] = mapped_column(Text, default="")
    waveform_color: Mapped[str] = mapped_column(String, default="#e2572c")
    download_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    exported_video_path: Mapped[str | None] = mapped_column(String, nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    episode: Mapped["Episode"] = relationship(back_populates="video")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"))
    index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String)
    start_ms: Mapped[int] = mapped_column(Integer)

    episode: Mapped["Episode"] = relationship(back_populates="chapters")


class GeneratedScript(TimestampMixin, Base):
    __tablename__ = "generated_scripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String, default="")
    research_text: Mapped[str] = mapped_column(Text, default="")
    outline: Mapped[list] = mapped_column(JSON, default=list)  # [str]
    script_text: Mapped[str] = mapped_column(Text, default="")
    llm_provider: Mapped[str] = mapped_column(String, default="")


class FeedEpisodeSuggestion(Base):
    __tablename__ = "feed_episode_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"), nullable=True)
    original_title: Mapped[str] = mapped_column(String, default="")
    original_description: Mapped[str] = mapped_column(Text, default="")
    suggested_title: Mapped[str] = mapped_column(String, default="")
    suggested_description: Mapped[str] = mapped_column(Text, default="")
    suggested_keywords: Mapped[list] = mapped_column(JSON, default=list)  # [str]
    used_transcript: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class SettingsKV(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class StatsCache(Base):
    __tablename__ = "stats_cache"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
