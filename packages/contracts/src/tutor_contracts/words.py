from datetime import datetime

from pydantic import BaseModel, Field

from tutor_contracts.turns import TurnProgress


class WordCardOut(BaseModel):
    """A flashcard for a word met in conversation. Clients show `word` first and reveal
    `translation` on request; the learner then says whether they knew it."""

    id: int
    word: str
    translation: str = Field(description="Meaning (for zh/ja it starts with the reading).")
    pos: str = ""
    box: int = Field(description="Spaced-repetition box: 0 = new or recently missed.")


class WordQueueOut(BaseModel):
    card: WordCardOut | None = Field(description="Next word due, or null when caught up.")
    due: int
    total: int = Field(description="All word cards for this learner.")
    next_due_at: datetime | None = None


class WordAnswerRequest(BaseModel):
    knew: bool = Field(description="The learner's own verdict (self-graded, no model call).")


class WordAnswerOut(BaseModel):
    knew: bool
    next_review_in_days: float
    due: int = Field(description="Words still due now.")
    progress: TurnProgress
