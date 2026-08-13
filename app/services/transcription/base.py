from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class WordTiming:
    word: str
    start_ms: int
    end_ms: int


@dataclass
class TranscriptSegmentResult:
    index: int
    start_ms: int
    end_ms: int
    text: str
    words: list[WordTiming] = field(default_factory=list)


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegmentResult]
    language: str | None
    duration_seconds: float | None

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments).strip()


class TranscriptionProvider(Protocol):
    def transcribe(self, audio_path: Path) -> TranscriptResult: ...
