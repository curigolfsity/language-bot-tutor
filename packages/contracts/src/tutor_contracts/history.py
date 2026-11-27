"""Past days of practice: day cards, a day's conversation, and the daily chat tidy."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from tutor_contracts.weekly import WeeklyTopicOut


class DayOut(BaseModel):
    """One local day of practice, in numbers."""

    day: date
    messages: int = Field(description="Messages the learner sent that day.")
    corrections: int
    new_words: int
    lessons: int
    top_mistakes: list[WeeklyTopicOut] = Field(default_factory=list)


class DayListOut(BaseModel):
    days: list[DayOut] = Field(description="Active days, newest first.")


class TranscriptFix(BaseModel):
    wrong: str
    right: str
    explanation: str


class TranscriptLine(BaseModel):
    role: Literal["learner", "tutor"]
    text: str
    at: datetime
    fixes: list[TranscriptFix] = Field(default_factory=list, description="On learner lines.")
    scenario_title: str | None = Field(
        default=None, description="Set on the first line of each conversation."
    )


class DayTranscriptOut(BaseModel):
    day: DayOut
    lines: list[TranscriptLine] = Field(description="That day's conversation turns, in order.")


class TidyOut(BaseModel):
    """A learner whose chat is due its daily tidy. Claiming marks it done for their local day."""

    profile_id: UUID
    external_id: str
    before: datetime = Field(description="Delete this language's messages sent before this.")
    days: list[DayOut] = Field(description="Days to leave a card for, oldest first.")
