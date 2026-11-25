"""Placement test: which question to ask next, and the suggested level. Pure functions.

Levels are tested from the lowest up, `per_level` questions each at most. A level is passed
with `pass_mark` right answers (asking stops early once that is certain either way). The test
ends at the first level that is not passed; the suggestion is the last level passed (the lowest
level if none was). Passing every level suggests the highest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tutor_api.curriculum.models import Placement, PlacementQuestion


@dataclass(frozen=True)
class Answered:
    question_id: str
    level: str
    correct: bool


@dataclass(frozen=True)
class LevelScore:
    level: str
    right: int
    asked: int


@dataclass(frozen=True)
class Step:
    question: PlacementQuestion | None  # next question, or None when finished
    result_level: str | None  # set when finished
    scores: tuple[LevelScore, ...]


def scores(ordered_levels: Sequence[str], answers: Sequence[Answered]) -> tuple[LevelScore, ...]:
    out = []
    for lv in ordered_levels:
        at = [a for a in answers if a.level == lv]
        if at:
            out.append(LevelScore(lv, sum(a.correct for a in at), len(at)))
    return tuple(out)


def next_step(
    placement: Placement,
    ordered_levels: Sequence[str],
    answers: Sequence[Answered],
    seed: int = 0,
) -> Step:
    """`seed` varies which question of a level's pool is asked (e.g. the run id)."""
    asked = {a.question_id for a in answers}
    passed: str | None = None
    for lv in ordered_levels:
        at = [a for a in answers if a.level == lv]
        right = sum(a.correct for a in at)
        if right >= placement.pass_mark:
            passed = lv
            continue
        failed = len(at) - right > placement.per_level - placement.pass_mark
        pool = [q for q in placement.questions if q.level == lv and q.id not in asked]
        if failed or not pool:
            break
        q = pool[(seed + len(at)) % len(pool)]
        return Step(question=q, result_level=None, scores=scores(ordered_levels, answers))
    return Step(
        question=None,
        result_level=passed or ordered_levels[0],
        scores=scores(ordered_levels, answers),
    )
