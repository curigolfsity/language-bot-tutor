"""Spaced repetition of learner mistakes (Leitner boxes). Pure functions only.

A card starts in box 0. A correct answer moves it up one box; a wrong answer sends it back to
box 0. The box sets how long until the card is due again.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

# Wait after a box-0 event (new card or failed answer): long enough to have moved on.
RETRY_DELAY = timedelta(minutes=10)
# Interval after a correct answer that lands the card in box N (index = N).
BOX_INTERVALS: tuple[timedelta, ...] = (
    RETRY_DELAY,
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
    timedelta(days=16),
    timedelta(days=35),
)
MAX_BOX = len(BOX_INTERVALS) - 1


@dataclass(frozen=True)
class Schedule:
    box: int
    due_at: datetime


def new_card(now: datetime) -> Schedule:
    return Schedule(box=0, due_at=now + RETRY_DELAY)


def after_answer(box: int, correct: bool, now: datetime) -> Schedule:
    if not correct:
        return Schedule(box=0, due_at=now + RETRY_DELAY)
    new_box = min(box + 1, MAX_BOX)
    return Schedule(box=new_box, due_at=now + BOX_INTERVALS[new_box])


def _norm(text: str) -> str:
    """Lowercase, NFC, punctuation dropped, whitespace collapsed. Accents stay significant."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def quick_grade(answer: str, wrong: str, right: str) -> bool | None:
    """Cheap, certain verdicts only: True when the answer contains the expected fix and not the
    original error. None means "not sure" (an alternative wording, a typo, a wrong answer):
    the caller asks the model.
    """
    a, w, r = _norm(answer), _norm(wrong), _norm(right)
    if not a or not r:
        return None
    padded = f" {a} "
    has_right = f" {r} " in padded
    has_wrong = bool(w) and f" {w} " in padded and f" {w} " not in f" {r} "
    if has_right and not has_wrong:
        return True
    return None
