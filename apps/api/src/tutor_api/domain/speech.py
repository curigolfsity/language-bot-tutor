"""What a spoken reply says. Pure functions."""

from __future__ import annotations

import re
from collections.abc import Sequence

MAX_SPEECH_CHARS = 1000  # a tutor reply is a few sentences; cap what is sent to the voice

# Emoji and pictographs (read aloud as names by some voices) and markup characters.
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0000fe0f\U0000200d\U00002b00-\U00002bff]"
)
_MARKUP = re.compile(r"[*_`#<>|~]")
_SPACES = re.compile(r"[ \t]+")


def speech_text(text: str, drop_patterns: Sequence[str] = ()) -> str:
    """The text to speak: language-specific `drop_patterns` (from language.yaml) removed,
    then emoji and markup, with whitespace tidied. Empty if nothing speakable is left."""
    for pattern in drop_patterns:
        text = re.sub(pattern, "", text)
    text = _MARKUP.sub("", _EMOJI.sub("", text))
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    out = "\n".join(line for line in lines if line)
    if len(out) > MAX_SPEECH_CHARS:
        cut = out[:MAX_SPEECH_CHARS]
        out = cut[: max(cut.rfind(" "), MAX_SPEECH_CHARS // 2)]
    return out
