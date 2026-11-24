"""Resolve the effective tutoring policy from levels.yaml + profile override + scenario."""

from __future__ import annotations

from dataclasses import dataclass

from tutor_api.curriculum.models import (
    CorrectTopics,
    Curriculum,
    ExplanationLanguage,
    Scenario,
)


@dataclass(frozen=True)
class Policy:
    target_lang: str
    target_lang_name: str
    native_lang: str
    level: str
    level_rank: int
    explanation_language: ExplanationLanguage
    max_corrections_per_turn: int
    correct_topics: CorrectTopics
    max_sentences: int
    vocab_ceiling: str
    speed_note: str
    focus_topics: tuple[str, ...] = ()

    def stable_key(self) -> tuple[object, ...]:
        """Fields that shape the cacheable system prompt (no per-learner data)."""
        return (
            self.target_lang,
            self.level,
            self.explanation_language,
            self.max_corrections_per_turn,
            self.correct_topics,
            self.max_sentences,
            self.vocab_ceiling,
        )


def resolve_policy(
    curriculum: Curriculum,
    level: str,
    native_lang: str,
    explanation_lang_override: ExplanationLanguage | None = None,
    scenario: Scenario | None = None,
) -> Policy:
    if not curriculum.has_level(level):
        raise ValueError(f"unknown level {level!r} for {curriculum.code}")
    lp = curriculum.levels[level]
    return Policy(
        target_lang=curriculum.code,
        target_lang_name=curriculum.lang.name,
        native_lang=native_lang,
        level=level,
        level_rank=lp.rank,
        explanation_language=explanation_lang_override or lp.explanation_language,
        max_corrections_per_turn=lp.max_corrections_per_turn,
        correct_topics=lp.correct_topics,
        max_sentences=lp.tutor_reply.max_sentences,
        vocab_ceiling=lp.tutor_reply.vocab_ceiling,
        speed_note=lp.tutor_reply.speed_note,
        focus_topics=scenario.target_topics if scenario else (),
    )
