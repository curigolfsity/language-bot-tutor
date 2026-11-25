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
    timezone: str = Field(description="IANA timezone used for daily streaks (effective value).")
    daily_goal: int = Field(description="Messages per day for the daily goal (effective value).")
    reminders_enabled: bool = True


class LearnerPatch(BaseModel):
    """Partial update. Omitted fields are left unchanged; `explanation_lang_override: null`
    clears the override."""

    cefr_level: str | None = None
    native_lang: str | None = Field(default=None, min_length=2, max_length=8)
    explanation_lang_override: ExplanationLanguage | None = None
    timezone: str | None = Field(default=None, max_length=64, description="IANA name")
    daily_goal: int | None = Field(default=None, ge=1, le=200)
    reminders_enabled: bool | None = None


class DailyProgressOut(BaseModel):
    streak: int = Field(description="Consecutive days practised, ending today or yesterday.")
    best_streak: int
    today: int = Field(description="Messages sent today (learner's local day).")
    goal: int
    goal_met: bool


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
