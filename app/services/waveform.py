import subprocess

import numpy as np

_SAMPLE_RATE = 8000
_ENVELOPE_RATE_HZ = 100  # one RMS sample per ~10ms — fine enough to drive 100ms attack/release ballistics
_ATTACK_S = 0.1
_RELEASE_S = 0.1


def _envelope_follower(values: np.ndarray, attack_s: float, release_s: float, rate_hz: float) -> np.ndarray:
    """Asymmetric exponential smoothing: rises over `attack_s`, decays over `release_s`.

    Mirrors a VU meter's ballistics so the waveform settles smoothly instead of jittering on
    every transient, while still tracking sustained loud/quiet passages.
    """
    if values.size == 0:
        return values
    attack_coeff = float(np.exp(-1.0 / (rate_hz * attack_s)))
    release_coeff = float(np.exp(-1.0 / (rate_hz * release_s)))
    smoothed = np.empty_like(values)
    level = float(values[0])
    for i, v in enumerate(values):
        coeff = attack_coeff if v > level else release_coeff
        level = coeff * level + (1 - coeff) * float(v)
        smoothed[i] = level
    return smoothed


def amplitude_envelope(audio_path: str, buckets: int = 36) -> list[float]:
    """Decodes audio to mono f32 PCM via ffmpeg and returns `buckets` normalized (0-1) envelope values.

    The raw signal is reduced to a fine RMS envelope (~10ms per sample), passed through an
    attack/release follower, then downsampled into `buckets` bars.
    """
    cmd = ["ffmpeg", "-v", "error", "-i", audio_path, "-f", "f32le", "-ac", "1", "-ar", str(_SAMPLE_RATE), "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    samples = np.frombuffer(proc.stdout, dtype="<f4")

    if samples.size == 0:
        return [0.1] * buckets

    frame_size = max(1, min(_SAMPLE_RATE // _ENVELOPE_RATE_HZ, samples.size))
    n_frames = samples.size // frame_size
    fine_chunks = samples[: n_frames * frame_size].reshape(n_frames, frame_size)
    fine_rms = np.sqrt(np.mean(fine_chunks**2, axis=1))
    fine_envelope = _envelope_follower(fine_rms, _ATTACK_S, _RELEASE_S, _ENVELOPE_RATE_HZ)

    bucket_chunks = np.array_split(fine_envelope, buckets)
    rms = np.array([chunk.mean() if chunk.size else 0.0 for chunk in bucket_chunks])
    peak = rms.max()
    if peak <= 1e-6:
        return [0.1] * buckets
    normalized = (rms / peak).clip(0.05, 1.0)
    return [round(float(v), 4) for v in normalized]
