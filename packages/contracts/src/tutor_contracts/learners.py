from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from tutor_contracts.common import ExplanationLanguage, Severity, Skill


class SkillLevelOut(BaseModel):
    skill: Skill
    cefr_level: str
    score: float


class LearnerProfileOut(BaseModel):
    id: UUID
    user_id: UUID
    target_lang: str
    native_lang: str
    cefr_level: str
    explanation_lang_override: ExplanationLanguage | None
    skills: list[SkillLevelOut]
    created_at: datetime


class LearnerPatch(BaseModel):
    """Partial update. Omitted fields are left unchanged; `explanation_lang_override: null`
    clears the override."""

    cefr_level: str | None = None
    native_lang: str | None = Field(default=None, min_length=2, max_length=8)
    explanation_lang_override: ExplanationLanguage | None = None


class MistakeOut(BaseModel):
    id: int
    wrong: str
    right: str
    rule_tag: str
    rule_title: str | None = None  # human-readable topic title
    explanation: str
    severity: Severity
    created_at: datetime


class VocabOut(BaseModel):
    lemma: str
    translation: str
    pos: str
    seen_count: int
    mastery: float
    last_seen_at: datetime
