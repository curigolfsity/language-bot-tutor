import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from tutor_api.services.context import AppContext


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


def require_client_key(
    ctx: Ctx, x_client_key: Annotated[str | None, Header(alias="X-Client-Key")] = None
) -> None:
    if not x_client_key or not any(
        secrets.compare_digest(x_client_key, k) for k in ctx.settings.client_api_keys
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid X-Client-Key")
