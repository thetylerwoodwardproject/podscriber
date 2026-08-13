from pathlib import Path

from app.services.transcription.base import TranscriptResult, TranscriptSegmentResult, WordTiming


class OpenAIWhisperProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment", "word"],
            )

        all_words = [
            WordTiming(word=w.word, start_ms=round(w.start * 1000), end_ms=round(w.end * 1000))
            for w in (resp.words or [])
        ]

        segments: list[TranscriptSegmentResult] = []
        for i, seg in enumerate(resp.segments or []):
            seg_start_ms = round(seg.start * 1000)
            seg_end_ms = round(seg.end * 1000)
            seg_words = [w for w in all_words if seg_start_ms <= w.start_ms < seg_end_ms]
            segments.append(
                TranscriptSegmentResult(
                    index=i,
                    start_ms=seg_start_ms,
                    end_ms=seg_end_ms,
                    text=seg.text.strip(),
                    words=seg_words,
                )
            )

        return TranscriptResult(segments=segments, language=resp.language, duration_seconds=resp.duration)
