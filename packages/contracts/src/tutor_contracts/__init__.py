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
from tutor_contracts.lessons import (
    ExerciseKind,
    ExerciseOut,
    LessonAnswerOut,
    LessonAnswerRequest,
    LessonExampleOut,
    LessonFormOut,
    LessonOut,
    LessonPartsOut,
    LessonSuggestionsOut,
    LessonTopicOut,
    LessonWatchOutOut,
    StartLessonRequest,
)
from tutor_contracts.placement import (
    PlacementAnswerRequest,
    PlacementFeedbackOut,
    PlacementLevelScoreOut,
    PlacementQuestionOut,
    PlacementResultOut,
    PlacementStepOut,
)
from tutor_contracts.reminders import ReminderClaimRequest, ReminderOut
from tutor_contracts.review import (
    ReviewAnswerOut,
    ReviewAnswerRequest,
    ReviewCardOut,
    ReviewQueueOut,
)
from tutor_contracts.sessions import (
    CreateSessionRequest,
    MistakeCount,
    SessionOut,
    SessionSummary,
)
from tutor_contracts.turns import (
    AskOut,
    AskRequest,
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
from tutor_contracts.weekly import WeeklySummaryOut, WeeklyTopicOut
from tutor_contracts.words import WordAnswerOut, WordAnswerRequest, WordCardOut, WordQueueOut

__all__ = [
    "AskOut",
    "AskRequest",
    "Correction",
    "CreateSessionRequest",
    "DailyProgressOut",
    "ExerciseKind",
    "ExerciseOut",
    "ExplanationLanguage",
    "GrammarTopicOut",
    "HealthOut",
    "HelpKind",
    "HelpOut",
    "HelpRequest",
    "LanguageOut",
    "LearnerPatch",
    "LearnerProfileOut",
    "LessonAnswerOut",
    "LessonAnswerRequest",
    "LessonExampleOut",
    "LessonFormOut",
    "LessonOut",
    "LessonPartsOut",
    "LessonSuggestionsOut",
    "LessonTopicOut",
    "LessonWatchOutOut",
    "LevelOut",
    "MistakeCount",
    "MistakeOut",
    "NewVocab",
    "PlacementAnswerRequest",
    "PlacementFeedbackOut",
    "PlacementLevelScoreOut",
    "PlacementQuestionOut",
    "PlacementResultOut",
    "PlacementStepOut",
    "ReminderClaimRequest",
    "ReminderOut",
    "ResolveUserRequest",
    "ResolveUserResponse",
    "ReviewAnswerOut",
    "ReviewAnswerRequest",
    "ReviewCardOut",
    "ReviewQueueOut",
    "ScenarioOut",
    "SessionMode",
    "SessionOut",
    "SessionSummary",
    "Severity",
    "Skill",
    "SkillLevelOut",
    "StartLessonRequest",
    "TopicRef",
    "TurnProgress",
    "TurnRequest",
    "TurnResponse",
    "TurnResult",
    "VocabOut",
    "WeeklySummaryOut",
    "WeeklyTopicOut",
    "WordAnswerOut",
    "WordAnswerRequest",
    "WordCardOut",
    "WordQueueOut",
]
