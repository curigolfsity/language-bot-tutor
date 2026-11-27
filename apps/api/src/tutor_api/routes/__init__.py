"""Thin HTTP layer: validate, call a service, return a DTO. No business logic here."""

from fastapi import APIRouter, Depends

from tutor_api.routes import (
    curriculum,
    health,
    history,
    learners,
    lessons,
    practice,
    reminders,
    review,
    sessions,
    turns,
    users,
)
from tutor_api.routes.deps import require_client_key

v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_client_key)])
v1.include_router(users.router)
v1.include_router(learners.router)
v1.include_router(curriculum.router)
v1.include_router(sessions.router)
v1.include_router(turns.router)
v1.include_router(reminders.router)
v1.include_router(review.router)
v1.include_router(lessons.learner_router)
v1.include_router(lessons.router)
v1.include_router(practice.learner_router)
v1.include_router(practice.router)
v1.include_router(history.learner_router)
v1.include_router(history.router)

__all__ = ["health", "v1"]
