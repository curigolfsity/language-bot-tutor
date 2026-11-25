from pydantic import BaseModel, Field


class PlacementQuestionOut(BaseModel):
    """A multiple-choice question. The right option is not sent until it is answered."""

    id: str
    level: str
    prompt: str = Field(description="Sentence with a gap (___).")
    options: list[str]
    number: int = Field(description="1-based question number in this test.")


class PlacementAnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=128)
    choice: int = Field(ge=0, le=9, description="0-based index into options.")


class PlacementFeedbackOut(BaseModel):
    correct: bool
    right_option: str


class PlacementLevelScoreOut(BaseModel):
    level: str
    right: int
    asked: int


class PlacementResultOut(BaseModel):
    """The suggested level. It is not applied: the learner chooses (PATCH the profile)."""

    level: str
    label: str = Field(description="Learner-facing description of the level.")
    can_do: str = ""
    current_level: str
    scores: list[PlacementLevelScoreOut]


class PlacementStepOut(BaseModel):
    run_id: int
    last: PlacementFeedbackOut | None = Field(default=None, description="The answer just given.")
    question: PlacementQuestionOut | None = Field(description="Next question; null when done.")
    result: PlacementResultOut | None = None
