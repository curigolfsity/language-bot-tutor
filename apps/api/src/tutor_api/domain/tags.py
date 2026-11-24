"""Sanitise model output against the curriculum and enforce the level policy."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

from tutor_contracts import Correction, TurnResult

from tutor_api.curriculum.models import Curriculum
from tutor_api.domain.policy import Policy
from tutor_api.domain.prompt import UNKNOWN_TAG


@dataclass(frozen=True)
class SanitizeReport:
    unknown_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyReport:
    violations: tuple[str, ...] = field(default_factory=tuple)


def sanitize_tags(
    result: TurnResult, known_ids: Collection[str]
) -> tuple[TurnResult, SanitizeReport]:
    """Map any rule_tag / grammar_tag that is not a curriculum id to "unknown"."""
    unknown: list[str] = []

    def fix(tag: str) -> str:
        tag = tag.strip()
        if tag in known_ids or tag == UNKNOWN_TAG:
            return tag
        unknown.append(tag)
        return UNKNOWN_TAG

    corrections = [c.model_copy(update={"rule_tag": fix(c.rule_tag)}) for c in result.corrections]
    tags: list[str] = []
    for t in result.grammar_tags:
        fixed = fix(t)
        if fixed not in tags:
            tags.append(fixed)
    clean = result.model_copy(update={"corrections": corrections, "grammar_tags": tags})
    return clean, SanitizeReport(unknown_tags=tuple(unknown))


def apply_policy(
    result: TurnResult, policy: Policy, curriculum: Curriculum
) -> tuple[TurnResult, PolicyReport]:
    """Safety net for the level policy. Expects tags already sanitised.

    - drops no-op corrections (wrong == right)
    - at `at_or_below_level`, drops corrections tagged with a topic above the learner's level
    - truncates to `max_corrections_per_turn`, keeping major ones first
    Each intervention is reported as a violation (the model should have done it itself).
    """
    violations: list[str] = []
    kept: list[Correction] = []
    for c in result.corrections:
        if c.wrong.strip() == c.right.strip():
            violations.append(f"noop_correction:{c.wrong!r}")
            continue
        if policy.correct_topics == "at_or_below_level" and c.rule_tag in curriculum.topics:
            topic_rank = curriculum.rank(curriculum.topics[c.rule_tag].level)
            if topic_rank > policy.level_rank:
                violations.append(f"above_level:{c.rule_tag}")
                continue
        kept.append(c)

    if len(kept) > policy.max_corrections_per_turn:
        violations.append(f"too_many_corrections:{len(kept)}>{policy.max_corrections_per_turn}")
        # stable sort: major before minor, otherwise keep the model's order
        kept = sorted(kept, key=lambda c: 0 if c.severity == "major" else 1)
        kept = kept[: policy.max_corrections_per_turn]

    return result.model_copy(update={"corrections": kept}), PolicyReport(tuple(violations))


MAX_PRAISED_TOPICS = 2


def well_done_topics(result: TurnResult, policy: Policy, curriculum: Curriculum) -> list[str]:
    """Topic ids the learner used correctly, for praise. Expects a sanitised, policy-applied result.

    Conservative on purpose: when the correction cap was reached, some errors may be hidden,
    so nothing is praised.
    """
    if len(result.corrections) >= policy.max_corrections_per_turn:
        return []
    corrected = {c.rule_tag for c in result.corrections}
    praised = [
        t
        for t in result.grammar_tags
        if t in curriculum.topics and t not in corrected and not curriculum.topics[t].deprecated
    ]
    return praised[:MAX_PRAISED_TOPICS]
