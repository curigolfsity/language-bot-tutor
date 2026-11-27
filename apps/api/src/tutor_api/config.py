import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


Effort = Literal["low", "medium", "high", "xhigh", "max"]


class LangRoute(BaseModel):
    """Per-language override for conversation turns (the correction path the eval covers)."""

    model: str | None = None
    effort: Effort | None = None
    fallbacks: Literal["default", "off"] | None = None  # some models have no server fallback
    # Only for these learner levels (level codes from levels.yaml); unset = every level.
    levels: list[str] | None = None

    def applies_to(self, level: str | None) -> bool:
        return self.levels is None or level in self.levels


class Settings(BaseSettings):
    """All runtime configuration. Values come from the environment or the repo-root `.env`."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8-sig", extra="ignore"
    )

    database_url: str = Field(alias="DATABASE_URL")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # LLM. The model id is configuration, never a literal in code paths.
    tutor_model: str = Field(default="claude-opus-5-5", alias="TUTOR_MODEL")
    # "low" matched "medium" on every correction-eval case at half the cost and a shorter
    # latency tail (evals/corrections/reports/*fix-low*). Raise it only on eval evidence.
    tutor_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="low", alias="TUTOR_EFFORT"
    )
    # Hint/translate/suggest/explain are simple and latency-sensitive: lower effort by default.
    tutor_help_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="low", alias="TUTOR_HELP_EFFORT"
    )
    # Habits (streaks, daily goal, reminders). Day boundaries use the learner's timezone,
    # falling back to DEFAULT_TIMEZONE (IANA name, e.g. Asia/Bangkok).
    default_timezone: str = Field(default="UTC", alias="DEFAULT_TIMEZONE")
    default_daily_goal: int = Field(default=10, ge=1, le=200, alias="DEFAULT_DAILY_GOAL")
    reminder_hour: int = Field(default=19, ge=0, le=23, alias="REMINDER_HOUR")
    reminder_max_idle_days: int = Field(default=7, ge=1, alias="REMINDER_MAX_IDLE_DAYS")
    # Weekly summary: sent on this local weekday (0 = Monday, 6 = Sunday) after REMINDER_HOUR.
    weekly_summary_weekday: int = Field(default=6, ge=0, le=6, alias="WEEKLY_SUMMARY_WEEKDAY")
    # Daily chat tidy: after this local hour, clients replace yesterday's messages with a card.
    tidy_hour: int = Field(default=4, ge=0, le=23, alias="TIDY_HOUR")

    # Voice messages: local speech-to-text (faster-whisper). Model files go to STT_MODEL_DIR.
    stt_enabled: bool = Field(default=True, alias="STT_ENABLED")
    stt_model: str = Field(default="small", alias="STT_MODEL")  # tiny | base | small | medium
    stt_model_dir: Path = Field(default=REPO_ROOT / ".models" / "whisper", alias="STT_MODEL_DIR")
    stt_max_seconds: float = Field(default=120.0, gt=0, alias="STT_MAX_SECONDS")
    stt_cpu_threads: int = Field(default=0, ge=0, alias="STT_CPU_THREADS")  # 0 = automatic

    # Spoken replies: edge-tts (online voices; only the reply text is sent). Voice per
    # language and speed per level come from the curriculum (language.yaml, levels.yaml).
    tts_enabled: bool = Field(default=True, alias="TTS_ENABLED")
    tts_timeout_seconds: float = Field(default=30.0, gt=0, alias="TTS_TIMEOUT_SECONDS")

    # Grammar lessons: correctness of generated exercises matters, so a notch more effort.
    lesson_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="medium", alias="LESSON_EFFORT"
    )
    lesson_exercises: int = Field(default=5, ge=1, le=10, alias="LESSON_EXERCISES")
    # A topic's explanation is written once (TUTOR_MODEL) and reused; repeat lessons only get
    # fresh exercises, from this model (unset: TUTOR_HELP_MODEL, then TUTOR_MODEL).
    lesson_exercise_model: str | None = Field(default=None, alias="LESSON_EXERCISE_MODEL")
    lesson_exercise_fallbacks: Literal["default", "off"] | None = Field(
        default=None, alias="LESSON_EXERCISE_FALLBACKS"
    )

    # Per-language routing for conversation turns, as JSON, e.g.
    # {"es": {"model": "claude-haiku-5-5", "effort": "medium", "fallbacks": "off"}}.
    # Decide it with the correction eval (evals/corrections, --lang); unlisted languages use
    # TUTOR_MODEL / TUTOR_EFFORT / TUTOR_FALLBACKS.
    tutor_lang_overrides: dict[str, LangRoute] = Field(
        default_factory=dict, alias="TUTOR_LANG_OVERRIDES"
    )

    # Model for the simple helper calls (hint, translate, suggest, explain, ask, answer
    # checking). Unset: TUTOR_MODEL. Haiku has no server-side refusal fallback -> "off".
    tutor_help_model: str | None = Field(default=None, alias="TUTOR_HELP_MODEL")
    tutor_help_fallbacks: Literal["default", "off"] | None = Field(
        default=None, alias="TUTOR_HELP_FALLBACKS"
    )

    tutor_max_tokens: int = Field(default=16000, alias="TUTOR_MAX_TOKENS")
    # "default" = server-side refusal fallbacks routed by the API; "off" disables them.
    tutor_fallbacks: Literal["default", "off"] = Field(default="default", alias="TUTOR_FALLBACKS")
    llm_timeout_seconds: float = Field(default=120.0, alias="LLM_TIMEOUT_SECONDS")

    # Client auth (Phase 1: shared keys per client app).
    client_api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="CLIENT_API_KEYS"
    )

    curriculum_dir: Path = Field(default=REPO_ROOT / "curriculum", alias="CURRICULUM_DIR")

    # Learner model.
    mastery_alpha: float = Field(default=0.2, gt=0, le=1, alias="MASTERY_ALPHA")
    recent_turns_in_prompt: int = Field(default=12, ge=0, alias="RECENT_TURNS_IN_PROMPT")

    @field_validator("client_api_keys", mode="before")
    @classmethod
    def _split_keys(cls, v: object) -> object:
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v

    @field_validator("tutor_lang_overrides", mode="before")
    @classmethod
    def _parse_overrides(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v) if v.strip() else {}
        return v

    @field_validator("default_timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown IANA timezone {v!r}") from e
        return v

    def for_lang(self, lang: str, level: str | None = None) -> "Settings":
        """These settings with `lang`'s turn route applied, if it covers `level` (with no
        level given, a route limited to some levels still applies: used to build clients)."""
        route = self.tutor_lang_overrides.get(lang)
        if route is None or (level is not None and not route.applies_to(level)):
            return self
        update = {
            k: v
            for k, v in {
                "tutor_model": route.model,
                "tutor_effort": route.effort,
                "tutor_fallbacks": route.fallbacks,
            }.items()
            if v is not None
        }
        return self.model_copy(update=update)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
