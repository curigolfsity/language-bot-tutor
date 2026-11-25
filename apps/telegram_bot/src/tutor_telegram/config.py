from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class BotSettings(BaseSettings):
    """Bot configuration only. The bot holds no learner state; everything lives in the API."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8-sig", extra="ignore"
    )

    telegram_token: str = Field(alias="TELEGRAM_TOKEN")
    api_base_url: str = Field(default="http://127.0.0.1:8000", alias="TUTOR_API_URL")
    # The X-Client-Key this client sends. Falls back to the first CLIENT_API_KEYS entry so a
    # single shared .env works in development.
    api_key: str | None = Field(default=None, alias="TUTOR_API_KEY")
    client_api_keys: str | None = Field(default=None, alias="CLIENT_API_KEYS")
    target_lang: str = Field(default="es", alias="BOT_TARGET_LANG")
    default_native_lang: str = Field(default="en", alias="BOT_DEFAULT_NATIVE_LANG")
    # Buttons offered for "explain things in..." (code:label, comma-separated). Presentation only;
    # any ISO 639-1 code also works via /native <code>.
    native_lang_choices: str = Field(
        default=(
            "en:English,th:ไทย,zh:中文,ja:日本語,ko:한국어,vi:Tiếng Việt,"
            "id:Bahasa Indonesia,de:Deutsch,fr:Français,pt:Português,it:Italiano,ru:Русский"
        ),
        alias="BOT_NATIVE_LANG_CHOICES",
    )
    request_timeout_seconds: float = Field(default=180.0, alias="BOT_REQUEST_TIMEOUT_SECONDS")
    # How often to ask the API who is due a practice reminder (the API decides who and when).
    # Small per-chat display state (foldable messages), kept across restarts. Not learner data.
    state_file: Path = Field(
        default=REPO_ROOT / ".run" / "bot_state.pickle", alias="BOT_STATE_FILE"
    )
    reminder_poll_seconds: float = Field(default=300.0, ge=30, alias="BOT_REMINDER_POLL_SECONDS")

    def native_choices(self) -> list[tuple[str, str]]:
        out = []
        for item in self.native_lang_choices.split(","):
            code, _, label = item.strip().partition(":")
            if code:
                out.append((code.strip(), label.strip() or code.strip()))
        return out

    @model_validator(mode="after")
    def _resolve_key(self) -> "BotSettings":
        if not self.api_key and self.client_api_keys:
            first = next((k.strip() for k in self.client_api_keys.split(",") if k.strip()), None)
            self.api_key = first
        if not self.api_key:
            raise ValueError("set TUTOR_API_KEY (or CLIENT_API_KEYS) so the bot can call the API")
        return self
