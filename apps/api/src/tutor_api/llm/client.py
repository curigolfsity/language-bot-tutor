"""The only module that talks to Anthropic.

Rules (see CLAUDE.md / docs/architecture.md section 6):
- structured outputs via `messages.parse` with the `TurnResult` Pydantic model
- no assistant prefill, no forced tool_choice
- model id and effort come from config
- `stop_reason == "refusal"` is handled, and server-side fallbacks are enabled by default
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from pydantic import BaseModel, Field
from tutor_contracts import NewVocab, TurnResult

from tutor_api.config import Settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """The model call failed or returned something unusable (not a refusal)."""


@dataclass(frozen=True)
class LLMTurnOutcome:
    result: TurnResult | None  # None when refused
    refused: bool
    refusal_category: str | None
    model: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class HelpText(BaseModel):
    """Structured output for a learner help request."""

    text: str = Field(description="The help text shown to the learner, plain text.")


@dataclass(frozen=True)
class LLMHelpOutcome:
    text: str | None  # None when refused
    refused: bool
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class ReviewGrade(BaseModel):
    """Structured output for grading a review answer."""

    correct: bool = Field(
        description="True if the learner's answer fixes the error correctly (any correct, "
        "natural wording counts)."
    )
    feedback: str = Field(description="One or two short sentences for the learner, plain text.")


@dataclass(frozen=True)
class LLMGradeOutcome:
    grade: ReviewGrade | None  # None when refused
    refused: bool
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class ExerciseSpec(BaseModel):
    kind: Literal["fill_blank", "fix", "translate"] = Field(
        description="fill_blank: complete the gap (___). fix: correct a sentence with one "
        "error. translate: translate a short sentence from the learner's language."
    )
    instruction: str = Field(description="One short line telling the learner what to do.")
    prompt: str = Field(description="The sentence to work on (use ___ for the gap).")
    answer: str = Field(
        description="The expected answer: the missing word(s) for fill_blank, the full "
        "corrected sentence for fix, the target-language sentence for translate."
    )
    also_accept: list[str] = Field(description="Other fully correct answers (may be empty).")
    why: str = Field(description="One short sentence explaining the answer.")


class FormLine(BaseModel):
    label: str = Field(description="Short label, e.g. '-ar verbs (hablar)', 'ser', '把 pattern'.")
    forms: str = Field(
        description="The forms or pattern, items separated by ' · '. Forms that change by "
        "person are written 'person: form', e.g. 'yo: hablaba · tú: hablabas · "
        "él/ella/usted: hablaba · nosotros: hablábamos · vosotros: hablabais · "
        "ellos/ustedes: hablaban'."
    )


class LessonExample(BaseModel):
    sentence: str = Field(description="Example sentence in the target language.")
    translation: str = Field(description="Its translation in the learner's native language.")


class WatchOut(BaseModel):
    wrong: str = Field(description="A typical wrong sentence (the learner's own if given).")
    right: str = Field(description="The corrected sentence.")
    note: str = Field(description="One short sentence: why.")


class LessonContent(BaseModel):
    """Structured output for a grammar lesson. Each part is laid out separately by clients."""

    summary: str = Field(description="One or two short sentences: what this grammar is for.")
    forms: list[FormLine] = Field(
        description="0-4 lines of forms to learn (conjugations, patterns). Empty if none."
    )
    usage: list[str] = Field(
        description="2-4 short points: when to use it, signal words. Each under 15 words."
    )
    examples: list[LessonExample] = Field(description="Exactly 3 examples, easiest first.")
    watch_out: WatchOut
    exercises: list[ExerciseSpec] = Field(description="Practice exercises, easiest first.")


class VocabList(BaseModel):
    """Structured output: dictionary entries for words the learner wants to keep."""

    items: list[NewVocab] = Field(description="One entry per word or expression, in order.")


@dataclass(frozen=True)
class LLMVocabOutcome:
    items: list[NewVocab] | None  # None when refused
    refused: bool
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class ExerciseSet(BaseModel):
    """Structured output: fresh exercises for a lesson whose explanation is reused."""

    exercises: list[ExerciseSpec] = Field(description="Practice exercises, easiest first.")


@dataclass(frozen=True)
class LLMExercisesOutcome:
    exercises: list[ExerciseSpec] | None  # None when refused
    refused: bool
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class LLMLessonOutcome:
    lesson: LessonContent | None  # None when refused
    refused: bool
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


def _usage(response: Any) -> dict[str, Any]:
    """Model and token counts of a response, for the outcome dataclasses."""
    u = response.usage
    return {
        "model": response.model,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_read_input_tokens": u.cache_read_input_tokens or 0,
        "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
    }


class TurnLLM(Protocol):
    """What services depend on. Tests provide a fake implementation."""

    model: str

    async def generate_turn(self, system_prompt: str, user_content: str) -> LLMTurnOutcome: ...

    async def generate_help(self, system_prompt: str, user_content: str) -> LLMHelpOutcome: ...

    async def generate_grade(self, system_prompt: str, user_content: str) -> LLMGradeOutcome: ...

    async def generate_lesson(self, system_prompt: str, user_content: str) -> LLMLessonOutcome: ...

    async def generate_exercises(
        self, system_prompt: str, user_content: str
    ) -> LLMExercisesOutcome: ...

    async def generate_vocab(self, system_prompt: str, user_content: str) -> LLMVocabOutcome: ...


class AnthropicTurnLLM:
    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.model = settings.tutor_model
        self._effort = settings.tutor_effort
        self._help_effort = settings.tutor_help_effort
        self._lesson_effort = settings.lesson_effort
        # Hint / translate / suggest / explain / ask / answer checking (simple, high-volume).
        self._help_model = settings.tutor_help_model or settings.tutor_model
        self._help_fallbacks = settings.tutor_help_fallbacks or settings.tutor_fallbacks
        # Fresh exercises for a reused lesson explanation: the help model unless set.
        self._exercise_model = settings.lesson_exercise_model or self._help_model
        self._exercise_fallbacks = settings.lesson_exercise_fallbacks or self._help_fallbacks
        self._max_tokens = settings.tutor_max_tokens
        self._fallbacks = settings.tutor_fallbacks
        self._client = client or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds
        )

    def variant(self, settings: Settings) -> AnthropicTurnLLM:
        """Same HTTP client, different model/effort settings (per-language routing)."""
        return AnthropicTurnLLM(settings, client=self._client)

    async def aclose(self) -> None:
        await self._client.close()

    async def _parse(
        self,
        system_prompt: str,
        user_content: str,
        output_format: type[BaseModel],
        effort: str,
        cache_system: bool,
        model: str | None = None,
        fallbacks: str | None = None,
    ) -> Any:
        """`model` / `fallbacks` default to the turn model and its fallback setting."""
        system_block: dict[str, Any] = {"type": "text", "text": system_prompt}
        if cache_system:
            system_block["cache_control"] = {"type": "ephemeral"}
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": self._max_tokens,
            "system": [system_block],
            "messages": [{"role": "user", "content": user_content}],
            "output_format": output_format,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }
        if (fallbacks or self._fallbacks) == "default":
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        try:
            response = await self._client.beta.messages.parse(**kwargs)
        except anthropic.APIConnectionError as e:
            raise LLMError(f"could not reach Anthropic: {e}") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Anthropic rate limit hit") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
        if response.stop_reason == "max_tokens":
            raise LLMError("model hit max_tokens before finishing its structured output")
        return response

    async def generate_turn(self, system_prompt: str, user_content: str) -> LLMTurnOutcome:
        # Stable prefix first, explicitly cached.
        response = await self._parse(
            system_prompt, user_content, TurnResult, self._effort, cache_system=True
        )
        usage = response.usage
        base = {
            "model": response.model,
            "stop_reason": response.stop_reason,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
        }

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            log.warning("model refused turn (category=%s, model=%s)", category, response.model)
            return LLMTurnOutcome(result=None, refused=True, refusal_category=category, **base)

        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed TurnResult (stop_reason={response.stop_reason})")
        return LLMTurnOutcome(result=parsed, refused=False, refusal_category=None, **base)

    async def generate_help(self, system_prompt: str, user_content: str) -> LLMHelpOutcome:
        response = await self._parse(
            system_prompt,
            user_content,
            HelpText,
            self._help_effort,
            cache_system=False,
            model=self._help_model,
            fallbacks=self._help_fallbacks,
        )
        base = _usage(response)
        if response.stop_reason == "refusal":
            log.warning("model refused help request (model=%s)", response.model)
            return LLMHelpOutcome(text=None, refused=True, **base)
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed HelpText (stop_reason={response.stop_reason})")
        return LLMHelpOutcome(text=parsed.text, refused=False, **base)

    async def generate_grade(self, system_prompt: str, user_content: str) -> LLMGradeOutcome:
        response = await self._parse(
            system_prompt,
            user_content,
            ReviewGrade,
            self._help_effort,
            cache_system=False,
            model=self._help_model,
            fallbacks=self._help_fallbacks,
        )
        if response.stop_reason == "refusal":
            log.warning("model refused review grading (model=%s)", response.model)
            return LLMGradeOutcome(grade=None, refused=True, **_usage(response))
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed ReviewGrade (stop_reason={response.stop_reason})")
        return LLMGradeOutcome(grade=parsed, refused=False, **_usage(response))

    async def generate_lesson(self, system_prompt: str, user_content: str) -> LLMLessonOutcome:
        # The system prompt holds the per-level teaching rules: cacheable across topics.
        response = await self._parse(
            system_prompt, user_content, LessonContent, self._lesson_effort, cache_system=True
        )
        if response.stop_reason == "refusal":
            log.warning("model refused lesson generation (model=%s)", response.model)
            return LLMLessonOutcome(lesson=None, refused=True, **_usage(response))
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed LessonContent (stop_reason={response.stop_reason})")
        return LLMLessonOutcome(lesson=parsed, refused=False, **_usage(response))

    async def generate_exercises(
        self, system_prompt: str, user_content: str
    ) -> LLMExercisesOutcome:
        response = await self._parse(
            system_prompt,
            user_content,
            ExerciseSet,
            self._lesson_effort,
            cache_system=False,
            model=self._exercise_model,
            fallbacks=self._exercise_fallbacks,
        )
        if response.stop_reason == "refusal":
            log.warning("model refused exercise generation (model=%s)", response.model)
            return LLMExercisesOutcome(exercises=None, refused=True, **_usage(response))
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed ExerciseSet (stop_reason={response.stop_reason})")
        return LLMExercisesOutcome(exercises=parsed.exercises, refused=False, **_usage(response))

    async def generate_vocab(self, system_prompt: str, user_content: str) -> LLMVocabOutcome:
        response = await self._parse(
            system_prompt,
            user_content,
            VocabList,
            self._help_effort,
            cache_system=False,
            model=self._help_model,
            fallbacks=self._help_fallbacks,
        )
        if response.stop_reason == "refusal":
            return LLMVocabOutcome(items=None, refused=True, **_usage(response))
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed VocabList (stop_reason={response.stop_reason})")
        return LLMVocabOutcome(items=parsed.items, refused=False, **_usage(response))
