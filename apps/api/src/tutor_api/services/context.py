from __future__ import annotations

from dataclasses import dataclass

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

    def curriculum(self, lang: str) -> Curriculum:
        try:
            return self.curricula[lang]
        except KeyError:
            raise InvalidRequestError(f"unsupported language {lang!r}") from None
