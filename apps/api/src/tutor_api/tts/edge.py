"""Spoken replies with edge-tts (Microsoft Edge's online neural voices; free, no key).

Only the tutor's reply text is sent to the service, never learner data or ids. The MP3 it
returns is converted to OGG/Opus so Telegram shows it as a voice message (falls back to MP3).
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import Protocol

import av
import edge_tts

log = logging.getLogger(__name__)


class TTSError(Exception):
    """Synthesis failed (network, unknown voice, empty audio)."""


@dataclass(frozen=True)
class Speech:
    audio: bytes
    mime: str  # "audio/ogg" or "audio/mpeg"


class TextToSpeech(Protocol):
    async def synthesize(self, text: str, voice: str, rate_percent: int = 0) -> Speech: ...


def _mp3_to_ogg_opus(mp3: bytes) -> bytes:
    out = io.BytesIO()
    with av.open(io.BytesIO(mp3)) as src, av.open(out, "w", format="ogg") as dst:
        stream = dst.add_stream("libopus", rate=48_000)
        stream.layout = "mono"  # type: ignore[union-attr]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48_000)
        for frame in src.decode(audio=0):
            for f in resampler.resample(frame):
                for packet in stream.encode(f):  # type: ignore[union-attr]
                    dst.mux(packet)
        for f in resampler.resample(None):
            for packet in stream.encode(f):  # type: ignore[union-attr]
                dst.mux(packet)
        for packet in stream.encode(None):  # type: ignore[union-attr]
            dst.mux(packet)
    return out.getvalue()


class EdgeTTS:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    async def _mp3(self, text: str, voice: str, rate_percent: int) -> bytes:
        comm = edge_tts.Communicate(text, voice, rate=f"{rate_percent:+d}%")
        chunks: list[bytes] = []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    async def synthesize(self, text: str, voice: str, rate_percent: int = 0) -> Speech:
        try:
            mp3 = await asyncio.wait_for(self._mp3(text, voice, rate_percent), self._timeout)
        except TimeoutError as e:
            raise TTSError("speech service timed out") from e
        except Exception as e:  # edge-tts raises several unrelated types
            raise TTSError(f"speech synthesis failed: {e}") from e
        if not mp3:
            raise TTSError("speech service returned no audio")
        try:
            return Speech(await asyncio.to_thread(_mp3_to_ogg_opus, mp3), "audio/ogg")
        except Exception as e:  # keep the reply audible even if the encoder is missing
            log.warning("OGG/Opus conversion failed, sending MP3: %s", e)
            return Speech(mp3, "audio/mpeg")
