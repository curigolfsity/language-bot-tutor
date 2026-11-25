"""Shared request/response DTOs: the API contract between `apps/api` and every client.

Clients depend on this package only. It holds no business logic and no I/O.
"""

from tutor_contracts.common import (
    ExplanationLanguage,
    HealthOut,
    SessionMode,
    Severity,
    Skill,
)
from tutor_contracts.curriculum import GrammarTopicOut, LanguageOut, LevelOut, ScenarioOut
from tutor_contracts.learners import (
    DailyProgressOut,
    LearnerPatch,
    LearnerProfileOut,
    MistakeOut,
    SkillLevelOut,
    VocabOut,
)
from tutor_contracts.reminders import ReminderClaimRequest, ReminderOut
from tutor_contracts.sessions import (
    CreateSessionRequest,
    MistakeCount,
    SessionOut,
    SessionSummary,
)
from tutor_contracts.turns import (
    Correction,
    HelpKind,
    HelpOut,
    HelpRequest,
    NewVocab,
    TopicRef,
    TurnProgress,
    TurnRequest,
    TurnResponse,
    TurnResult,
)
from tutor_contracts.users import ResolveUserRequest, ResolveUserResponse

__all__ = [
    "DailyProgressOut",
    "ReminderClaimRequest",
    "ReminderOut",
    "TurnProgress",
    "TurnResponse",
    "TopicRef",
    "LanguageOut",
    "HelpRequest",
    "HelpOut",
    "HelpKind",
    "Correction",
    "CreateSessionRequest",
    "ExplanationLanguage",
    "GrammarTopicOut",
    "HealthOut",
    "LearnerPatch",
    "LearnerProfileOut",
    "LevelOut",
    "MistakeCount",
    "MistakeOut",
    "NewVocab",
    "ResolveUserRequest",
    "ResolveUserResponse",
    "ScenarioOut",
    "SessionMode",
    "SessionOut",
    "SessionSummary",
    "Severity",
    "Skill",
    "SkillLevelOut",
    "TurnRequest",
    "TurnResult",
    "VocabOut",
]
