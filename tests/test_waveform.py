import numpy as np

from app.services.waveform import _envelope_follower


def test_envelope_follower_rises_and_decays_gradually():
    # A step from silence to full level: with 100ms attack at a 100Hz update rate, the follower
    # shouldn't jump straight to 1.0 — it should still be climbing after the first few frames.
    values = np.array([0.0] * 5 + [1.0] * 20)
    smoothed = _envelope_follower(values, attack_s=0.1, release_s=0.1, rate_hz=100)
    assert smoothed[5] < 0.5  # just stepped up, hasn't caught up yet
    assert smoothed[-1] > 0.8  # given enough frames, converges toward the sustained level


def test_envelope_follower_decays_gradually_after_transient():
    values = np.array([1.0] * 5 + [0.0] * 20)
    smoothed = _envelope_follower(values, attack_s=0.1, release_s=0.1, rate_hz=100)
    assert smoothed[5] > 0.5  # just dropped, hasn't decayed yet
    assert smoothed[-1] < 0.2  # given enough frames, settles back toward silence


def test_envelope_follower_empty_input():
    assert _envelope_follower(np.array([]), 0.1, 0.1, 100).size == 0


def test_envelope_follower_constant_input_stays_constant():
    values = np.full(10, 0.5)
    smoothed = _envelope_follower(values, attack_s=0.1, release_s=0.1, rate_hz=100)
    assert np.allclose(smoothed, 0.5)
