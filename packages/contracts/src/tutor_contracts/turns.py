from typing import Literal

from pydantic import BaseModel, Field

from tutor_contracts.common import Severity


class Correction(BaseModel):
    wrong: str = Field(description="The exact erroneous span copied from the learner's message.")
    right: str = Field(description="The corrected version of that span.")
    rule_tag: str = Field(
        description="Curriculum topic id from the catalogue that this error violates, "
        'or "unknown" if none fits.'
    )
    explanation: str = Field(
        description="One or two short sentences, in the explanation language the policy requires."
    )
    severity: Severity = Field(
        description='"major" if it hinders meaning or is a core error at this level, else "minor".'
    )


class NewVocab(BaseModel):
    lemma: str = Field(description="Dictionary form of a word or fixed expression the tutor used.")
    translation: str = Field(description="Translation into the learner's native language.")
    pos: str = Field(description="Part of speech, e.g. noun, verb, adjective, phrase.")


class TurnResult(BaseModel):
    """One tutor turn as produced by the LLM (its structured-output schema).

    Changing this model changes what the LLM must produce: re-run the correction eval.
    """

    reply: str = Field(
        description="The tutor's in-character reply in the target language, at the learner's level."
    )
    corrections: list[Correction] = Field(
        description="Corrections of the learner's latest message only, most important first."
    )
    new_vocab: list[NewVocab] = Field(
        description="Words from the tutor's reply that are likely new to the learner (0-3 items)."
    )
    grammar_tags: list[str] = Field(
        description="Curriculum topic ids that the learner's latest message exercised, "
        "whether used correctly or not."
    )


class TopicRef(BaseModel):
    id: str
    title: str


class TurnResponse(TurnResult):
    """API response for a turn: the validated TurnResult plus server-computed extras.

    The extras are not produced by the LLM, so adding them does not change the LLM schema.
    """

    turn_id: int = Field(description="Id of the tutor turn; use it for /v1/turns/{id}/help.")
    well_done: list[TopicRef] = Field(
        default_factory=list,
        description="Topics the learner used correctly in this message (for praise).",
    )


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


HelpKind = Literal["hint", "translate", "suggest", "explain"]


class HelpRequest(BaseModel):
    kind: HelpKind


class HelpOut(BaseModel):
    kind: HelpKind
    text: str
