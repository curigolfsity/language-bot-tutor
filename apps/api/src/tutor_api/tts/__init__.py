"""Text-to-speech. The only package that imports the TTS engine (edge-tts)."""

from tutor_api.tts.edge import EdgeTTS, Speech, TextToSpeech, TTSError

__all__ = ["EdgeTTS", "Speech", "TTSError", "TextToSpeech"]
