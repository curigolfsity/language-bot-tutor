from fastapi import APIRouter
from tutor_contracts import ReminderClaimRequest, ReminderOut

from tutor_api.routes.deps import Ctx
from tutor_api.services import habits_service

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.post("/claim", response_model=list[ReminderOut])
async def claim(body: ReminderClaimRequest, ctx: Ctx) -> list[ReminderOut]:
    """Learners of this client who are due a practice reminder now. Each is returned at most
    once per local day; the client sends the message."""
    return await habits_service.claim_reminders(ctx, body.provider, body.target_lang)
