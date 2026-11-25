"""Immutable in-memory curriculum, parsed from `curriculum/<lang>/`.

These are plain value objects (no I/O), so `domain/` may import them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ExplanationLanguage = Literal["native", "mixed", "target"]
CorrectTopics = Literal["at_or_below_level", "all", "all_plus_style"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Example(_Strict):
    wrong: str
    right: str


class GrammarTopic(_Strict):
    id: str = Field(pattern=r"^[a-z]{2,3}\.[a-c][12]\.[a-z0-9_]+$")
    level: str
    title: str
    description: str
    prerequisites: tuple[str, ...] = ()
    examples: tuple[Example, ...] = ()
    deprecated: bool = False


class Scenario(_Strict):
    id: str = Field(pattern=r"^[a-z]{2,3}\.[a-c][12]\.[a-z0-9_]+$")
    level: str
    title: str
    setting: str
    bot_role: str
    goals: tuple[str, ...]
    target_topics: tuple[str, ...]
    key_vocab: tuple[str, ...] = ()
    opening_line: str
    deprecated: bool = False


class TutorReplyPolicy(_Strict):
    max_sentences: int = Field(ge=1)
    vocab_ceiling: str
    speed_note: str = ""
    # Spoken replies: speaking-rate change in percent (negative = slower), e.g. -25 at A1.
    speech_rate: int = Field(default=0, ge=-50, le=50)


class LevelPolicy(_Strict):
    code: str
    rank: int = Field(ge=1)
    explanation_language: ExplanationLanguage
    max_corrections_per_turn: int = Field(ge=0)
    correct_topics: CorrectTopics
    tutor_reply: TutorReplyPolicy
    free_opening: str
    # Learner-facing description (plain words, not CEFR jargon).
    label: str
    can_do: str = ""
    starter_scenario: str | None = None


class LanguageMeta(_Strict):
    code: str
    name: str
    native_name: str
    flag: str = ""  # emoji shown next to the language name in clients
    refusal_reply: str
    prompt_notes: tuple[str, ...] = ()
    # Optional text that steers speech-to-text (e.g. Simplified vs Traditional Chinese).
    stt_prompt: str = ""
    # Spoken replies (text-to-speech): the voice name, and regexes removed from the text
    # before speaking (e.g. readings in brackets, so 学生（がくせい） is not read twice).
    tts_voice: str = ""
    speech_drop: tuple[str, ...] = ()

    @field_validator("speech_drop")
    @classmethod
    def _valid_regexes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in v:
            re.compile(pattern)
        return v


class PlacementQuestion(_Strict):
    id: str = Field(pattern=r"^[a-z]{2,3}\.place\.[a-z0-9_]+$")
    level: str
    prompt: str
    options: tuple[str, ...] = Field(min_length=2, max_length=4)
    answer: int = Field(ge=0, description="0-based index of the correct option")
    hint: str = ""  # optional, in English: what the sentence means


class Placement(_Strict):
    """Placement test (placement.yaml): multiple-choice questions, asked level by level.
    A level is passed with `pass_mark` right out of `per_level` questions."""

    per_level: int = Field(ge=1)
    pass_mark: int = Field(ge=1)
    questions: tuple[PlacementQuestion, ...]


@dataclass(frozen=True)
class Curriculum:
    lang: LanguageMeta
    levels: dict[str, LevelPolicy]
    topics: dict[str, GrammarTopic]
    scenarios: dict[str, Scenario]
    placement: Placement | None = None
    _ordered_levels: tuple[str, ...] = field(default=(), repr=False)

    @property
    def code(self) -> str:
        return self.lang.code

    @property
    def ordered_levels(self) -> tuple[str, ...]:
        """Level codes from lowest to highest rank."""
        return self._ordered_levels or tuple(sorted(self.levels, key=lambda c: self.levels[c].rank))

    @property
    def lowest_level(self) -> str:
        return self.ordered_levels[0]

    def rank(self, level: str) -> int:
        return self.levels[level].rank

    def has_level(self, level: str) -> bool:
        return level in self.levels

    def topic_ids(self) -> frozenset[str]:
        return frozenset(self.topics)

    def topics_at(self, level: str) -> list[GrammarTopic]:
        return [t for t in self.topics.values() if t.level == level and not t.deprecated]

    def topics_up_to(self, level: str) -> list[GrammarTopic]:
        r = self.rank(level)
        return [t for t in self.topics.values() if self.rank(t.level) <= r and not t.deprecated]

    def active_topics(self) -> list[GrammarTopic]:
        return [t for t in self.topics.values() if not t.deprecated]

    def scenarios_near(self, level: str, spread: int = 1) -> list[Scenario]:
        r = self.rank(level)
        return [
            s
            for s in self.scenarios.values()
            if not s.deprecated and abs(self.rank(s.level) - r) <= spread
        ]
