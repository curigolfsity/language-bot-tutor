"""FastAPI app. Run with: uv run uvicorn tutor_api.main:app --reload"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from tutor_api.config import get_settings
from tutor_api.curriculum import load_all_curricula
from tutor_api.db import make_engine, make_sessionmaker
from tutor_api.llm import AnthropicTurnLLM
from tutor_api.routes import health, v1
from tutor_api.services.context import AppContext
from tutor_api.services.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    ServiceError,
    UnavailableError,
    UpstreamError,
)
from tutor_api.stt import WhisperSTT

log = logging.getLogger("tutor_api")

_STATUS: dict[type[ServiceError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidRequestError: status.HTTP_400_BAD_REQUEST,
    UnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    UpstreamError: status.HTTP_502_BAD_GATEWAY,
}


def create_app(ctx: AppContext | None = None) -> FastAPI:
    """Build the app. Tests pass a ready AppContext; production builds one from settings."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if ctx is not None:
            app.state.ctx = ctx
            yield
            return
        settings = get_settings()
        if not settings.client_api_keys:
            raise RuntimeError("CLIENT_API_KEYS is empty; refusing to start")
        # Refuses to start on an invalid curriculum (raises CurriculumError).
        curricula = load_all_curricula(settings.curriculum_dir)
        engine = make_engine(settings.database_url)
        llm = AnthropicTurnLLM(settings)
        stt = None
        if settings.stt_enabled:
            stt = WhisperSTT(
                settings.stt_model,
                settings.stt_model_dir,
                settings.stt_max_seconds,
                settings.stt_cpu_threads,
            )
            # Load (first time: download) in the background so the first voice note is fast.
            app.state.stt_warmup = asyncio.create_task(asyncio.to_thread(stt.load))
        app.state.ctx = AppContext(
            settings=settings,
            curricula=curricula,
            sessionmaker=make_sessionmaker(engine),
            llm=llm,
            stt=stt,
        )
        log.info("tutor API ready: model=%s effort=%s", settings.tutor_model, settings.tutor_effort)
        try:
            yield
        finally:
            await llm.aclose()
            await engine.dispose()

    app = FastAPI(title="Spanish Tutor API", version="0.1.0", lifespan=lifespan)
    if ctx is not None:
        app.state.ctx = ctx  # available even when the ASGI lifespan isn't run (tests)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        code = next(
            (c for t, c in _STATUS.items() if isinstance(exc, t)),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    app.include_router(health.router)
    app.include_router(v1)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
