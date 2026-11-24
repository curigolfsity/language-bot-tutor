from fastapi import APIRouter
from tutor_contracts import HealthOut

from tutor_api.routes.deps import Ctx

router = APIRouter()


@router.get("/healthz", response_model=HealthOut)
async def healthz(ctx: Ctx) -> HealthOut:
    return HealthOut(status="ok", languages=sorted(ctx.curricula))
