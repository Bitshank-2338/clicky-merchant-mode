"""The speech-to-text path must not go through PyAV.

faster-whisper decodes anything that is not already a numpy array by calling
`av.open(..., metadata_errors="ignore")`. PyAV 19.0 removed that argument, so on
any environment that resolves to PyAV >= 19 the decode raises

    TypeError: open() got an unexpected keyword argument 'metadata_errors'

and every spoken word is lost (clicky-windows issue #24). Clicky already holds
16kHz mono PCM16, so it hands over samples and the decoder is never reached.

These tests fail if anyone reintroduces a file path or a WAV blob.
"""

import asyncio

import numpy as np
import pytest

from audio.capture import SAMPLE_RATE, pcm16_to_float32


def _tone(seconds: float = 0.5, rate: int = SAMPLE_RATE, freq: float = 440.0) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    return (np.sin(2 * np.pi * freq * t) * 8000).astype(np.int16).tobytes()


class _SpyModel:
    """Stands in for WhisperModel and records what it was handed."""

    def __init__(self):
        self.audio = None

    def transcribe(self, audio, **kwargs):
        self.audio = audio

        class _Seg:
            text = " hello "

        return [_Seg()], None


# ── pcm16_to_float32 ─────────────────────────────────────────────────────────

def test_float32_conversion_is_normalised():
    audio = pcm16_to_float32(_tone())
    assert audio.dtype == np.float32
    assert audio.size == SAMPLE_RATE // 2
    assert np.all(np.abs(audio) <= 1.0)


def test_float32_resamples_when_the_rate_is_not_16k():
    # PyAV used to resample on our behalf. Nothing does now, so this must.
    audio = pcm16_to_float32(_tone(seconds=1.0, rate=8000), sample_rate=8000)
    assert abs(audio.size - SAMPLE_RATE) <= 1


def test_float32_survives_empty_input():
    assert pcm16_to_float32(b"").size == 0


# ── the two call sites that used to write a temp WAV ─────────────────────────

def test_faster_whisper_hands_the_model_samples_not_a_path(monkeypatch):
    from audio.stt import faster_whisper_stt

    spy = _SpyModel()
    monkeypatch.setattr(faster_whisper_stt, "_get_model", lambda: spy)

    text = asyncio.run(faster_whisper_stt.FasterWhisperSTT().transcribe(_tone()))

    assert text == "hello"
    assert isinstance(spy.audio, np.ndarray), (
        f"model received {type(spy.audio).__name__}; anything but an ndarray "
        "sends faster-whisper into PyAV, which breaks on PyAV >= 19"
    )
    assert spy.audio.dtype == np.float32


def test_wake_word_listener_hands_the_model_samples_not_a_path(monkeypatch):
    from audio.ambient_listener import AmbientListener

    spy = _SpyModel()
    listener = AmbientListener.__new__(AmbientListener)   # no audio device needed
    monkeypatch.setattr(listener, "_get_model", lambda: spy, raising=False)

    assert listener._transcribe_tiny(_tone(seconds=0.3)).strip() == "hello"
    assert isinstance(spy.audio, np.ndarray)


def test_decode_audio_is_never_called(monkeypatch):
    """The belt-and-braces check: blow up if faster-whisper's decoder is used."""
    faster_whisper_audio = pytest.importorskip("faster_whisper.audio")

    def _explode(*args, **kwargs):
        raise AssertionError("decode_audio was called — PyAV is back in the path")

    monkeypatch.setattr(faster_whisper_audio, "decode_audio", _explode)

    from audio.stt import faster_whisper_stt

    spy = _SpyModel()
    monkeypatch.setattr(faster_whisper_stt, "_get_model", lambda: spy)
    asyncio.run(faster_whisper_stt.FasterWhisperSTT().transcribe(_tone()))
