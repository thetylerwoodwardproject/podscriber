from pathlib import Path

from app.services.transcription.base import TranscriptResult, TranscriptSegmentResult, WordTiming

_model_cache: dict[str, object] = {}


def _get_model(model_size: str):
    if model_size not in _model_cache:
        from faster_whisper import WhisperModel

        _model_cache[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model_cache[model_size]


class LocalWhisperProvider:
    def __init__(self, model_size: str = "small"):
        self.model_size = model_size

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        model = _get_model(self.model_size)
        segments_iter, info = model.transcribe(str(audio_path), word_timestamps=True)

        segments: list[TranscriptSegmentResult] = []
        for i, seg in enumerate(segments_iter):
            words = [
                WordTiming(word=w.word.strip(), start_ms=round(w.start * 1000), end_ms=round(w.end * 1000))
                for w in (seg.words or [])
            ]
            segments.append(
                TranscriptSegmentResult(
                    index=i,
                    start_ms=round(seg.start * 1000),
                    end_ms=round(seg.end * 1000),
                    text=seg.text.strip(),
                    words=words,
                )
            )

        return TranscriptResult(segments=segments, language=info.language, duration_seconds=info.duration)
