from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class WeeklyTopicOut(BaseModel):
    id: str
    title: str
    count: int = Field(default=0, description="Mistakes on it this week (0 for suggestions).")


class WeeklySummaryOut(BaseModel):
    """The learner's last 7 local days (today included)."""

    profile_id: UUID
    external_id: str | None = Field(default=None, description="Set in claimed summaries.")
    first_day: date
    last_day: date
    days_active: int
    messages: int
    streak: int
    best_streak: int
    lessons: int
    exercises_right: int
    exercises_done: int
    mistakes: int
    top_mistakes: list[WeeklyTopicOut]
    new_words: int
    reviews_due: int = Field(description="Mistake cards due now.")
    words_due: int = Field(description="Word flashcards due now.")
    suggested_lesson: WeeklyTopicOut | None = None
