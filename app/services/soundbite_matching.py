"""Maps an LLM-selected quote (plain text) back to precise timestamps in the transcript.

The LLM only returns quoted text, not timestamps, so we fuzzy-match that text against
the transcript's word-level (or segment-level, as a fallback) timing data.
"""

import difflib
import re
from dataclasses import dataclass

from app.models import TranscriptSegment


@dataclass
class _WordEntry:
    text: str
    start_ms: int
    end_ms: int


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _flatten_words(segments: list[TranscriptSegment]) -> list[_WordEntry]:
    entries: list[_WordEntry] = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                entries.append(_WordEntry(text=w["word"], start_ms=w["start_ms"], end_ms=w["end_ms"]))
        else:
            entries.append(_WordEntry(text=seg.text, start_ms=seg.start_ms, end_ms=seg.end_ms))
    return entries


def quote_coverage(segments: list[TranscriptSegment], quote: str) -> float:
    """Returns what fraction of `quote` appears as one contiguous run in the transcript (0.0-1.0).

    A genuine verbatim quote should score close to 1.0. Low scores catch degenerate LLM
    output (e.g. leaked reasoning or malformed-JSON retry text) that isn't actually drawn
    from the episode, so callers can discard it instead of saving/showing it as a soundbite.
    """
    words = _flatten_words(segments)
    quote_norm = _normalize(quote)
    if not words or not quote_norm:
        return 0.0
    joined = " ".join(_normalize(w.text) for w in words)
    matcher = difflib.SequenceMatcher(None, joined, quote_norm, autojunk=False)
    match = matcher.find_longest_match(0, len(joined), 0, len(quote_norm))
    return match.size / len(quote_norm)


def match_quote_to_timestamps(segments: list[TranscriptSegment], quote: str) -> tuple[int, int]:
    """Returns (start_ms, end_ms) for the best match of `quote` in the transcript.

    Falls back to the whole-episode span if no reasonable match is found, which keeps
    the pipeline from crashing on an LLM quote that doesn't appear verbatim.
    """
    words = _flatten_words(segments)
    if not words:
        return 0, 0

    normalized_words = [_normalize(w.text) for w in words]
    joined = " ".join(normalized_words)
    # char offset -> word index, at each word's starting position in `joined`
    offsets: list[int] = []
    pos = 0
    for nw in normalized_words:
        offsets.append(pos)
        pos += len(nw) + 1

    quote_norm = _normalize(quote)
    if not quote_norm:
        return words[0].start_ms, words[-1].end_ms

    matcher = difflib.SequenceMatcher(None, joined, quote_norm, autojunk=False)
    match = matcher.find_longest_match(0, len(joined), 0, len(quote_norm))

    if match.size < max(6, len(quote_norm) // 3):
        # Weak match — fall back to whole-segment best match via a coarser comparison.
        best_seg, best_ratio = None, 0.0
        for seg in segments:
            ratio = difflib.SequenceMatcher(None, _normalize(seg.text), quote_norm).ratio()
            if ratio > best_ratio:
                best_seg, best_ratio = seg, ratio
        if best_seg is not None:
            return best_seg.start_ms, best_seg.end_ms
        return words[0].start_ms, words[-1].end_ms

    start_char, end_char = match.a, match.a + match.size

    def word_index_for_char(char_pos: int) -> int:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= char_pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    start_idx = word_index_for_char(start_char)
    end_idx = word_index_for_char(max(start_char, end_char - 1))
    return words[start_idx].start_ms, words[end_idx].end_ms
