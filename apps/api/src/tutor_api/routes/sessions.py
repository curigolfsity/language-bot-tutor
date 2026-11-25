from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from tutor_contracts import (
    CreateSessionRequest,
    SessionOut,
    SessionSummary,
    TurnRequest,
    TurnResponse,
)

from tutor_api.routes.deps import Ctx
from tutor_api.services import session_service, turn_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(body: CreateSessionRequest, ctx: Ctx) -> SessionOut:
    return await session_service.start_session(ctx, body)


@router.post("/{session_id}/turns", response_model=TurnResponse)
async def post_turn(session_id: UUID, body: TurnRequest, ctx: Ctx) -> TurnResponse:
    return await turn_service.handle_turn(ctx, session_id, body.text)


MAX_AUDIO_BYTES = 20 * 1024 * 1024


@router.post("/{session_id}/turns/voice", response_model=TurnResponse)
async def post_voice_turn(
    session_id: UUID, ctx: Ctx, audio: Annotated[UploadFile, File()]
) -> TurnResponse:
    """A spoken turn (any common audio format, e.g. Telegram's OGG/Opus voice notes).
    The response's `transcript` is what was heard."""
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "audio file too large")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty audio file")
    return await turn_service.handle_voice_turn(ctx, session_id, data)


@router.post("/{session_id}/end", response_model=SessionSummary)
async def end_session(session_id: UUID, ctx: Ctx) -> SessionSummary:
    return await session_service.end_session(ctx, session_id)
