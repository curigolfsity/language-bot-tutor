from uuid import UUID

from pydantic import BaseModel, Field


class ReminderClaimRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32, examples=["telegram"])
    target_lang: str = Field(min_length=2, max_length=8, examples=["es"])


class ReminderOut(BaseModel):
    """A learner to remind now. Claiming marks them reminded for their local day."""

    profile_id: UUID
    external_id: str
    streak: int = Field(description="Streak at risk (0 if it already lapsed).")
    goal: int
