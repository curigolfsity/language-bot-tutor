"""Speech-to-text. The only package that imports the STT engine (faster-whisper)."""

from tutor_api.stt.whisper import (
    AudioTooLongError,
    SpeechToText,
    STTError,
    Transcript,
    WhisperSTT,
)

__all__ = ["AudioTooLongError", "STTError", "SpeechToText", "Transcript", "WhisperSTT"]
