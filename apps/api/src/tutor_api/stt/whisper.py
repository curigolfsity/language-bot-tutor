"""Local speech-to-text with faster-whisper (CPU, int8). Free and private: audio never leaves
the machine. The model is downloaded once into STT_MODEL_DIR (on D:, not the user cache).

Caveat: Whisper's language model can quietly "fix" small grammar slips while transcribing, so
voice turns may get fewer corrections than the same words typed. The learner sees the
transcript and can tell when that happened.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import av
import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # what Whisper models expect


class STTError(Exception):
    """Transcription failed (bad audio, engine error)."""


class AudioTooLongError(STTError):
    pass


@dataclass(frozen=True)
class Transcript:
    text: str
    duration_seconds: float


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, language: str) -> Transcript: ...


class WhisperSTT:
    def __init__(
        self, model_size: str, model_dir: Path, max_seconds: float, cpu_threads: int = 0
    ) -> None:
        self._model_size = model_size
        self._model_dir = model_dir
        self._max_seconds = max_seconds
        self._cpu_threads = cpu_threads
        self._model = None
        self._load_lock = threading.Lock()
        self._run_lock = asyncio.Lock()  # one transcription at a time: it uses every CPU core

    def load(self) -> None:
        """Load (and on first use download) the model. Blocking; safe to call repeatedly."""
        with self._load_lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel  # heavy import, deferred

            self._model_dir.mkdir(parents=True, exist_ok=True)
            log.info("loading whisper model %r from %s", self._model_size, self._model_dir)
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=self._cpu_threads,
                download_root=str(self._model_dir),
            )
            log.info("whisper model ready")

    @staticmethod
    def _decode(audio: bytes) -> np.ndarray:
        """Any container/codec PyAV reads -> 16 kHz mono float32, as Whisper expects.

        Done here rather than by faster-whisper, whose decoder breaks on newer PyAV releases.
        """
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        chunks: list[np.ndarray] = []
        with av.open(io.BytesIO(audio)) as container:
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32) / 32768.0

    def _run(self, audio: bytes, language: str) -> Transcript:
        self.load()
        assert self._model is not None
        try:
            samples = self._decode(audio)
            duration = len(samples) / SAMPLE_RATE
            if duration > self._max_seconds:
                raise AudioTooLongError(
                    f"voice message is {duration:.0f}s; the limit is {self._max_seconds:.0f}s"
                )
            if duration == 0:
                return Transcript(text="", duration_seconds=0.0)
            segments, _info = self._model.transcribe(
                samples,
                language=language,
                beam_size=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=True,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        except STTError:
            raise
        except Exception as e:  # decoding errors from PyAV / ctranslate2
            raise STTError(f"could not transcribe audio: {e}") from e
        return Transcript(text=text, duration_seconds=duration)

    async def transcribe(self, audio: bytes, language: str) -> Transcript:
        async with self._run_lock:
            return await asyncio.to_thread(self._run, audio, language)
