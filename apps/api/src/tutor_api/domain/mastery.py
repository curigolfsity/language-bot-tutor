"""Learner-model math (see docs/architecture.md section 8). Pure functions only."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from tutor_contracts import Correction, Severity

from tutor_api.domain.prompt import UNKNOWN_TAG
from tutor_api.domain.text import contains_unit

SEVERITY_WEIGHT: dict[Severity, float] = {"major": 1.0, "minor": 0.5}


@dataclass(frozen=True)
class TopicState:
    mastery: float = 0.0
    attempts: int = 0
    errors: int = 0


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def on_correct_use(m: float, alpha: float) -> float:
    """m <- m + alpha * (1 - m)"""
    return _clamp(m + alpha * (1.0 - m))


def on_error(m: float, alpha: float, severity: Severity) -> float:
    """m <- m - alpha * m * w   (w = 1.0 major, 0.5 minor)"""
    return _clamp(m - alpha * m * SEVERITY_WEIGHT[severity])


def topic_updates(
    grammar_tags: Iterable[str],
    corrections: Sequence[Correction],
    current: Mapping[str, TopicState],
    alpha: float,
) -> dict[str, TopicState]:
    """New state for every topic touched by this turn.

    Each correction counts as one error on its rule_tag. A grammar_tag with no correction on the
    same topic counts as one correct use. "unknown" is never tracked.
    """
    out: dict[str, TopicState] = {}

    def state(tid: str) -> TopicState:
        return out.get(tid) or current.get(tid) or TopicState()

    errored: set[str] = set()
    for c in corrections:
        if c.rule_tag == UNKNOWN_TAG:
            continue
        s = state(c.rule_tag)
        out[c.rule_tag] = TopicState(
            mastery=on_error(s.mastery, alpha, c.severity),
            attempts=s.attempts + 1,
            errors=s.errors + 1,
        )
        errored.add(c.rule_tag)

    for tid in dict.fromkeys(grammar_tags):
        if tid == UNKNOWN_TAG or tid in errored:
            continue
        s = state(tid)
        out[tid] = TopicState(
            mastery=on_correct_use(s.mastery, alpha), attempts=s.attempts + 1, errors=s.errors
        )
    return out


def normalize_text(text: str) -> str:
    """Lowercase, NFC, punctuation -> space, collapse whitespace. Accents are kept."""
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(text: str, phrase: str) -> bool:
    """Word-boundary phrase match on normalised text."""
    return contains_unit(normalize_text(text), normalize_text(phrase))


def vocab_used_correctly(
    learner_text: str, lemmas: Iterable[str], corrections: Sequence[Correction]
) -> set[str]:
    """Known lemmas the learner used in this message outside any corrected span."""
    used = set()
    for lemma in lemmas:
        if not contains_phrase(learner_text, lemma):
            continue
        if any(contains_phrase(c.wrong, lemma) for c in corrections):
            continue
        used.add(lemma)
    return used


def aggregate_score(masteries: Sequence[float]) -> float:
    """Skill score from aggregates (never from a single turn): the mean mastery, 0 when empty."""
    return round(sum(masteries) / len(masteries), 4) if masteries else 0.0
