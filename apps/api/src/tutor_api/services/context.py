from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tutor_api.config import Settings
from tutor_api.curriculum import Curriculum
from tutor_api.llm import TurnLLM
from tutor_api.services.errors import InvalidRequestError
from tutor_api.stt import SpeechToText


@dataclass
class AppContext:
    """Long-lived dependencies, built once at startup and shared by all services."""

    settings: Settings
    curricula: dict[str, Curriculum]
    sessionmaker: async_sessionmaker[AsyncSession]
    llm: TurnLLM
    stt: SpeechToText | None = None  # None: voice messages disabled
    # Conversation-turn LLMs routed per target language (TUTOR_LANG_OVERRIDES); others use llm.
    turn_llms: dict[str, TurnLLM] = field(default_factory=dict)

    def turn_llm(self, lang: str, level: str | None = None) -> TurnLLM:
        route = self.settings.tutor_lang_overrides.get(lang)
        if route is not None and not route.applies_to(level):
            return self.llm
        return self.turn_llms.get(lang, self.llm)

    def curriculum(self, lang: str) -> Curriculum:
        try:
            return self.curricula[lang]
        except KeyError:
            raise InvalidRequestError(f"unsupported language {lang!r}") from None
