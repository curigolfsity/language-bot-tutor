from fastapi import APIRouter, Response
from tutor_contracts import HelpOut, HelpRequest

from tutor_api.routes.deps import Ctx
from tutor_api.services import help_service, speech_service

router = APIRouter(prefix="/turns", tags=["turns"])


@router.post("/{turn_id}/help", response_model=HelpOut)
async def turn_help(turn_id: int, body: HelpRequest, ctx: Ctx) -> HelpOut:
    """Hint, translation, suggested answer or deeper explanation for a tutor message."""
    return await help_service.get_help(ctx, turn_id, body.kind)


@router.get("/{turn_id}/speech", response_class=Response)
async def turn_speech(turn_id: int, ctx: Ctx) -> Response:
    """The tutor message read aloud (OGG/Opus, or MP3 if conversion is unavailable)."""
    speech = await speech_service.turn_speech(ctx, turn_id)
    return Response(content=speech.audio, media_type=speech.mime)
