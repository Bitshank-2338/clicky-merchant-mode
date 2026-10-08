import io
import asyncio
from typing import Optional

from audio.stt.base_stt import BaseSTT
from audio.capture import pcm16_to_float32, trim_silence
from config import cfg

_model_cache = None


def _get_model():
    global _model_cache
    if _model_cache is None:
        from faster_whisper import WhisperModel
        # compute_type="int8" runs on CPU without CUDA; use "float16" if GPU available
        _model_cache = WhisperModel(cfg.whisper_model, device="cpu", compute_type="int8")
    return _model_cache


class FasterWhisperSTT(BaseSTT):
    """
    Local, offline speech-to-text using faster-whisper.
    No API key required. Runs entirely on CPU.
    Model is loaded once and cached.
    """

    async def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        pcm_bytes = trim_silence(pcm_bytes)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run, pcm_bytes, sample_rate)

    def _run(self, pcm_bytes: bytes, sample_rate: int) -> str:
        # Samples, not a file — faster-whisper only reaches for PyAV when it is
        # handed something it has to decode. See `pcm16_to_float32`.
        audio = pcm16_to_float32(pcm_bytes, sample_rate)
        if audio.size == 0:
            return ""
        model = _get_model()
        lang = cfg.whisper_language or None  # None = auto-detect
        segments, _ = model.transcribe(audio, beam_size=5, language=lang)
        return " ".join(s.text.strip() for s in segments).strip()
