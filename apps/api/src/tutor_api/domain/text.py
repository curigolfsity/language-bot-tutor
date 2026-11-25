"""Text matching that works for languages with and without spaces between words. Pure.

Spanish words are matched on word boundaries ("mi" must not match inside "amigo"). Chinese and
Japanese are written without spaces, so there a phrase matches as a plain substring.
"""

from __future__ import annotations

import re

# Hiragana, katakana, CJK unified ideographs (+ extension A), CJK compatibility ideographs.
_UNSPACED_SCRIPT = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")


def is_unspaced(text: str) -> bool:
    """True if the text uses a script written without spaces between words."""
    return bool(_UNSPACED_SCRIPT.search(text))


def contains_unit(haystack: str, needle: str) -> bool:
    """`needle` occurs in `haystack` as a whole word/phrase. Both must already be normalised
    (lowercase, punctuation removed, single spaces)."""
    if not needle:
        return False
    if is_unspaced(needle):
        return needle in haystack
    return f" {needle} " in f" {haystack} "
