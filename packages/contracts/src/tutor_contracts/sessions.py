from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from tutor_contracts.common import SessionMode
from tutor_contracts.learners import VocabOut


class CreateSessionRequest(BaseModel):
    profile_id: UUID
    scenario_id: str | None = None


class SessionOut(BaseModel):
    id: UUID
    profile_id: UUID
    mode: SessionMode
    scenario_id: str | None
    scenario_title: str | None
    level_at_start: str
    started_at: datetime
    ended_at: datetime | None
    opening_line: str
    opening_turn_id: int | None = None


class MistakeCount(BaseModel):
    rule_tag: str
    title: str | None = None
    count: int


class SessionSummary(BaseModel):
    session_id: UUID
    turn_count: int
    top_mistakes: list[MistakeCount]
    new_vocab: list[VocabOut]
