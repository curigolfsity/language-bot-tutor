from datetime import datetime

from pydantic import BaseModel, Field

from tutor_contracts.turns import TurnProgress


class ReviewCardOut(BaseModel):
    """A past mistake to fix. The correct form is not sent until the learner answers."""

    id: int
    source_text: str = Field(description="The learner's original message containing the error.")
    wrong: str = Field(description="The erroneous span inside source_text (to highlight).")
    rule_tag: str
    rule_title: str | None = None
    box: int = Field(description="Spaced-repetition box: 0 = new or recently missed.")


class ReviewQueueOut(BaseModel):
    card: ReviewCardOut | None = Field(description="Next card due, or null when caught up.")
    due: int = Field(description="Cards due now, including `card`.")
    total: int = Field(description="All cards for this learner.")
    next_due_at: datetime | None = Field(description="When the next card is due if none now.")


class ReviewAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=1000)


class ReviewAnswerOut(BaseModel):
    correct: bool
    wrong: str = Field(description="The original error.")
    right: str = Field(description="A correct fix for the error.")
    explanation: str
    feedback: str | None = Field(description="Model feedback when the answer needed judging.")
    next_review_in_days: float
    due: int = Field(description="Cards still due now.")
    progress: TurnProgress
