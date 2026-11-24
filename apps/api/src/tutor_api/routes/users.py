from fastapi import APIRouter
from tutor_contracts import ResolveUserRequest, ResolveUserResponse

from tutor_api.routes.deps import Ctx
from tutor_api.services import learner_service

router = APIRouter(tags=["users"])


@router.post("/users/resolve", response_model=ResolveUserResponse)
async def resolve_user(body: ResolveUserRequest, ctx: Ctx) -> ResolveUserResponse:
    return await learner_service.resolve_user(ctx, body)
