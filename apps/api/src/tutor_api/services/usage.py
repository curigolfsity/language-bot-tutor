"""Record token usage of non-turn model calls (help, ask, grade, lesson)."""

from __future__ import annotations

import logging
from typing import Any

from tutor_api.db.models import LlmCall
from tutor_api.services.context import AppContext

log = logging.getLogger(__name__)


async def record_call(ctx: AppContext, kind: str, lang: str | None, outcome: Any) -> None:
    """Best effort: a failure to log usage never fails the learner's request."""
    try:
        async with ctx.sessionmaker.begin() as db:
            db.add(
                LlmCall(
                    kind=kind,
                    lang=lang,
                    model=outcome.model,
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                    cache_read_input_tokens=outcome.cache_read_input_tokens,
                    cache_creation_input_tokens=outcome.cache_creation_input_tokens,
                )
            )
    except Exception:
        log.exception("could not record %s usage", kind)
