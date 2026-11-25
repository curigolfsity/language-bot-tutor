from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


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

    # Voice messages: local speech-to-text (faster-whisper). Model files go to STT_MODEL_DIR.
    stt_enabled: bool = Field(default=True, alias="STT_ENABLED")
    stt_model: str = Field(default="small", alias="STT_MODEL")  # tiny | base | small | medium
    stt_model_dir: Path = Field(default=REPO_ROOT / ".models" / "whisper", alias="STT_MODEL_DIR")
    stt_max_seconds: float = Field(default=120.0, gt=0, alias="STT_MAX_SECONDS")
    stt_cpu_threads: int = Field(default=0, ge=0, alias="STT_CPU_THREADS")  # 0 = automatic

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

    @field_validator("default_timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown IANA timezone {v!r}") from e
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
