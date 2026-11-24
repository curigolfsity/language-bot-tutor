from __future__ import annotations

import uuid
from typing import get_args

from sqlalchemy.exc import IntegrityError
from tutor_contracts import (
    LearnerPatch,
    LearnerProfileOut,
    MistakeOut,
    ResolveUserRequest,
    ResolveUserResponse,
    SessionOut,
    Skill,
    VocabOut,
)

from tutor_api.db.repositories import (
    MistakeRepo,
    ProfileRepo,
    SessionRepo,
    TurnRepo,
    UserRepo,
    VocabRepo,
)
from tutor_api.services.context import AppContext
from tutor_api.services.errors import InvalidRequestError, NotFoundError
from tutor_api.services.mappers import mistake_out, profile_out, session_out, vocab_out

SKILLS: tuple[str, ...] = get_args(Skill)


async def resolve_user(ctx: AppContext, req: ResolveUserRequest) -> ResolveUserResponse:
    """Idempotent: find or create the user (by identity) and their profile for target_lang."""
    curriculum = ctx.curriculum(req.target_lang)
    for attempt in range(2):
        try:
            async with ctx.sessionmaker.begin() as db:
                users, profiles = UserRepo(db), ProfileRepo(db)
                user = await users.get_by_identity(req.provider, req.external_id)
                if user is None:
                    user = await users.create_with_identity(
                        req.provider, req.external_id, req.display_name
                    )
                profile = await profiles.get_for_user(user.id, req.target_lang)
                created = profile is None
                if profile is None:
                    level = curriculum.lowest_level
                    profile = await profiles.create(
                        user.id, req.target_lang, req.native_lang, level
                    )
                    for skill in SKILLS:
                        await profiles.upsert_skill(profile.id, skill, level)
                skills = await profiles.skills(profile.id)
                return ResolveUserResponse(
                    user_id=user.id, profile=profile_out(profile, skills), created=created
                )
        except IntegrityError:
            # A concurrent resolve created the same identity/profile; the retry will find it.
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


async def get_profile(ctx: AppContext, profile_id: uuid.UUID) -> LearnerProfileOut:
    async with ctx.sessionmaker() as db:
        profiles = ProfileRepo(db)
        profile = await profiles.get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        return profile_out(profile, await profiles.skills(profile.id))


async def patch_profile(
    ctx: AppContext, profile_id: uuid.UUID, patch: LearnerPatch
) -> LearnerProfileOut:
    async with ctx.sessionmaker.begin() as db:
        profiles = ProfileRepo(db)
        profile = await profiles.get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        curriculum = ctx.curriculum(profile.target_lang)
        fields = patch.model_fields_set

        if "cefr_level" in fields and patch.cefr_level is not None:
            if not curriculum.has_level(patch.cefr_level):
                raise InvalidRequestError(
                    f"unknown level {patch.cefr_level!r}; valid: {list(curriculum.ordered_levels)}"
                )
            # Level changes are confirmed by the learner (this call); keep skills in step.
            profile.cefr_level = patch.cefr_level
            for skill in SKILLS:
                await profiles.upsert_skill(profile.id, skill, patch.cefr_level)
        if "native_lang" in fields and patch.native_lang is not None:
            profile.native_lang = patch.native_lang
        if "explanation_lang_override" in fields:
            profile.explanation_lang_override = patch.explanation_lang_override
        await db.flush()
        return profile_out(profile, await profiles.skills(profile.id))


async def list_mistakes(
    ctx: AppContext, profile_id: uuid.UUID, topic: str | None, limit: int
) -> list[MistakeOut]:
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        cur = ctx.curriculum(profile.target_lang)
        return [mistake_out(m, cur) for m in await MistakeRepo(db).list(profile_id, topic, limit)]


async def list_vocab(ctx: AppContext, profile_id: uuid.UUID, limit: int) -> list[VocabOut]:
    async with ctx.sessionmaker() as db:
        if await ProfileRepo(db).get(profile_id) is None:
            raise NotFoundError("learner profile not found")
        return [vocab_out(v) for v in await VocabRepo(db).list(profile_id, limit)]


async def active_session(ctx: AppContext, profile_id: uuid.UUID) -> SessionOut:
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        session = await SessionRepo(db).get_open(profile_id)
        if session is None:
            raise NotFoundError("no active session")
        first = await TurnRepo(db).first(session.id)
        return session_out(
            session,
            first.text if first else "",
            ctx.curriculum(profile.target_lang),
            first.id if first else None,
        )
