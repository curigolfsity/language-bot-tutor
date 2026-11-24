from fastapi import APIRouter
from tutor_contracts import HelpOut, HelpRequest

from tutor_api.routes.deps import Ctx
from tutor_api.services import help_service

router = APIRouter(prefix="/turns", tags=["turns"])


@router.post("/{turn_id}/help", response_model=HelpOut)
async def turn_help(turn_id: int, body: HelpRequest, ctx: Ctx) -> HelpOut:
    """Hint, translation, suggested answer or deeper explanation for a tutor message."""
    return await help_service.get_help(ctx, turn_id, body.kind)
