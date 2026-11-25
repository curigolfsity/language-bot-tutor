"""Grammar lessons: which topics to suggest, and checking exercise answers. Pure functions.

Suggestions come from the learner model and the curriculum's order:
  1. "weak": topics already practised with low mastery, most errors first
  2. "next": topics at the learner's level not practised yet, whose prerequisites have been
     practised, in curriculum order (the YAML order respects prerequisites)
  3. "refresh": anything else at or below the level, lowest mastery first (fills the list)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from tutor_api.curriculum.models import GrammarTopic
from tutor_api.domain.review import normalize_answer

WEAK_MASTERY = 0.6  # below this, a practised topic counts as weak

Reason = Literal["weak", "next", "refresh"]


@dataclass(frozen=True)
class TopicStats:
    mastery: float
    attempts: int
    errors: int


@dataclass(frozen=True)
class Suggestion:
    topic_id: str
    reason: Reason


def suggest_topics(
    topics: Sequence[GrammarTopic],
    level: str,
    stats: Mapping[str, TopicStats],
    limit: int = 6,
    max_weak: int = 3,
) -> list[Suggestion]:
    """`topics`: active topics at or below the learner's level, in curriculum order."""
    out: list[Suggestion] = []
    seen: set[str] = set()

    def add(tid: str, reason: Reason) -> None:
        if tid not in seen and len(out) < limit:
            out.append(Suggestion(tid, reason))
            seen.add(tid)

    practised = {tid for tid, s in stats.items() if s.attempts > 0}
    weak = sorted(
        (t for t in topics if t.id in practised and stats[t.id].mastery < WEAK_MASTERY),
        key=lambda t: (-stats[t.id].errors, stats[t.id].mastery),
    )
    for t in weak[:max_weak]:
        add(t.id, "weak")

    for t in topics:
        ready = all(p in practised for p in t.prerequisites)
        if t.level == level and t.id not in practised and ready:
            add(t.id, "next")
    for t in topics:  # prerequisites not met yet: still better than nothing
        if t.level == level and t.id not in practised:
            add(t.id, "next")

    rest = sorted(
        (t for t in topics if t.id not in seen),
        key=lambda t: stats[t.id].mastery if t.id in stats else 0.0,
    )
    for t in rest:
        add(t.id, "refresh")
    return out


def check_exercise(answer: str, accepted: Sequence[str]) -> bool | None:
    """True if the answer matches an accepted answer (ignoring case, punctuation and extra
    spaces; accents count). None means "not sure": the caller asks the model."""
    a = normalize_answer(answer)
    if not a:
        return None
    if any(a == normalize_answer(x) for x in accepted if x.strip()):
        return True
    return None


def lesson_plain_text(parts: dict) -> str:
    """The lesson parts as readable plain text (for clients without rich layout)."""
    lines = [parts["summary"].strip()]
    if parts.get("forms"):
        lines.append("")
        lines += [f"{f['label']}: {f['forms']}" for f in parts["forms"]]
    if parts.get("usage"):
        lines.append("")
        lines += [f"• {u}" for u in parts["usage"]]
    if parts.get("examples"):
        lines.append("")
        lines += [f"{e['sentence']} ({e['translation']})" for e in parts["examples"]]
    w = parts.get("watch_out")
    if w:
        lines += ["", f"Watch out: ✗ {w['wrong']} → ✓ {w['right']}. {w['note']}".rstrip()]
    return "\n".join(lines)
