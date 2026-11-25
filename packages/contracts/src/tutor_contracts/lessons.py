from typing import Literal

from pydantic import BaseModel, Field

from tutor_contracts.turns import TurnProgress

ExerciseKind = Literal["fill_blank", "fix", "translate"]


class LessonTopicOut(BaseModel):
    id: str
    title: str
    level: str
    mastery: float | None = Field(description="0-1, or null if never practised.")
    lessons_taken: int = 0
    reason: Literal["weak", "next", "refresh"] | None = Field(
        default=None, description="Why it is suggested (suggestions only)."
    )


class LessonSuggestionsOut(BaseModel):
    suggested: list[LessonTopicOut] = Field(description="Best topics to study now, in order.")
    level_topics: list[LessonTopicOut] = Field(description="Every topic at the learner's level.")


class StartLessonRequest(BaseModel):
    topic_id: str = Field(min_length=1, max_length=128)


class ExerciseOut(BaseModel):
    """One exercise. The expected answer is not sent until the learner answers."""

    index: int = Field(description="0-based position in the lesson.")
    total: int
    kind: ExerciseKind
    instruction: str
    prompt: str


class LessonOut(BaseModel):
    id: int
    topic: LessonTopicOut
    explanation: str
    exercise: ExerciseOut | None = Field(description="The first exercise.")


class LessonAnswerRequest(BaseModel):
    index: int = Field(ge=0)
    answer: str = Field(min_length=1, max_length=1000)


class LessonAnswerOut(BaseModel):
    correct: bool
    expected: str = Field(description="The model answer.")
    why: str
    feedback: str | None = Field(description="Model feedback when the answer needed judging.")
    score: int = Field(description="Correct answers so far.")
    answered: int
    total: int
    next: ExerciseOut | None = Field(description="Next exercise, or null when the lesson is over.")
    mastery: float = Field(description="Topic mastery (0-1) after this answer.")
    progress: TurnProgress
