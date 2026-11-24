from uuid import UUID

from fastapi import APIRouter, status
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


@router.post("/{session_id}/end", response_model=SessionSummary)
async def end_session(session_id: UUID, ctx: Ctx) -> SessionSummary:
    return await session_service.end_session(ctx, session_id)
