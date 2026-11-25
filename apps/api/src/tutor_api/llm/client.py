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
from tutor_contracts import TurnResult

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


class LessonContent(BaseModel):
    """Structured output for a grammar lesson."""

    explanation: str = Field(description="The lesson text shown to the learner, plain text.")
    exercises: list[ExerciseSpec] = Field(description="Practice exercises, easiest first.")


@dataclass(frozen=True)
class LLMLessonOutcome:
    lesson: LessonContent | None  # None when refused
    refused: bool
    model: str


class TurnLLM(Protocol):
    """What services depend on. Tests provide a fake implementation."""

    model: str

    async def generate_turn(self, system_prompt: str, user_content: str) -> LLMTurnOutcome: ...

    async def generate_help(self, system_prompt: str, user_content: str) -> LLMHelpOutcome: ...

    async def generate_grade(self, system_prompt: str, user_content: str) -> LLMGradeOutcome: ...

    async def generate_lesson(self, system_prompt: str, user_content: str) -> LLMLessonOutcome: ...


class AnthropicTurnLLM:
    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.model = settings.tutor_model
        self._effort = settings.tutor_effort
        self._help_effort = settings.tutor_help_effort
        self._lesson_effort = settings.lesson_effort
        self._max_tokens = settings.tutor_max_tokens
        self._fallbacks = settings.tutor_fallbacks
        self._client = client or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def _parse(
        self,
        system_prompt: str,
        user_content: str,
        output_format: type[BaseModel],
        effort: str,
        cache_system: bool,
    ) -> Any:
        system_block: dict[str, Any] = {"type": "text", "text": system_prompt}
        if cache_system:
            system_block["cache_control"] = {"type": "ephemeral"}
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": [system_block],
            "messages": [{"role": "user", "content": user_content}],
            "output_format": output_format,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }
        if self._fallbacks == "default":
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
            system_prompt, user_content, HelpText, self._help_effort, cache_system=False
        )
        base = {
            "model": response.model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        if response.stop_reason == "refusal":
            log.warning("model refused help request (model=%s)", response.model)
            return LLMHelpOutcome(text=None, refused=True, **base)
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed HelpText (stop_reason={response.stop_reason})")
        return LLMHelpOutcome(text=parsed.text, refused=False, **base)

    async def generate_grade(self, system_prompt: str, user_content: str) -> LLMGradeOutcome:
        response = await self._parse(
            system_prompt, user_content, ReviewGrade, self._help_effort, cache_system=False
        )
        if response.stop_reason == "refusal":
            log.warning("model refused review grading (model=%s)", response.model)
            return LLMGradeOutcome(grade=None, refused=True, model=response.model)
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed ReviewGrade (stop_reason={response.stop_reason})")
        return LLMGradeOutcome(grade=parsed, refused=False, model=response.model)

    async def generate_lesson(self, system_prompt: str, user_content: str) -> LLMLessonOutcome:
        # The system prompt holds the per-level teaching rules: cacheable across topics.
        response = await self._parse(
            system_prompt, user_content, LessonContent, self._lesson_effort, cache_system=True
        )
        if response.stop_reason == "refusal":
            log.warning("model refused lesson generation (model=%s)", response.model)
            return LLMLessonOutcome(lesson=None, refused=True, model=response.model)
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no parsed LessonContent (stop_reason={response.stop_reason})")
        return LLMLessonOutcome(lesson=parsed, refused=False, model=response.model)
