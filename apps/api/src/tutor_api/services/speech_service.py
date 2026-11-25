"""Spoken replies: a tutor message as audio, in the target language's voice."""

from __future__ import annotations

import logging

from tutor_api.db.models import LearnerProfile
from tutor_api.db.repositories import ProfileRepo, SessionRepo, TurnRepo, VocabRepo
from tutor_api.domain.speech import speech_text
from tutor_api.services.context import AppContext
from tutor_api.services.errors import (
    InvalidRequestError,
    NotFoundError,
    UnavailableError,
    UpstreamError,
)
from tutor_api.tts import Speech, TTSError

log = logging.getLogger(__name__)


async def _speak(ctx: AppContext, profile: LearnerProfile, text: str) -> Speech:
    if ctx.tts is None:
        raise UnavailableError("spoken replies are turned off on this server")
    curriculum = ctx.curriculum(profile.target_lang)
    voice = curriculum.lang.tts_voice
    if not voice:
        raise UnavailableError(f"no voice configured for {curriculum.lang.name}")
    text = speech_text(text, curriculum.lang.speech_drop)
    if not text:
        raise InvalidRequestError("nothing to speak in this message")
    rate = curriculum.levels[profile.cefr_level].tutor_reply.speech_rate
    try:
        return await ctx.tts.synthesize(text, voice, rate)
    except TTSError as e:
        log.error("TTS failed: %s", e)
        raise UpstreamError(str(e)) from e


async def turn_speech(ctx: AppContext, turn_id: int) -> Speech:
    async with ctx.sessionmaker() as db:
        turn = await TurnRepo(db).get(turn_id)
        if turn is None:
            raise NotFoundError("turn not found")
        if turn.role != "tutor":
            raise InvalidRequestError("only tutor messages can be spoken")
        session = await SessionRepo(db).get(turn.session_id)
        assert session is not None
        profile = await ProfileRepo(db).get(session.profile_id)
        assert profile is not None
    return await _speak(ctx, profile, turn.text)


async def word_speech(ctx: AppContext, word_id: int) -> Speech:
    async with ctx.sessionmaker() as db:
        item = await VocabRepo(db).get(word_id)
        if item is None:
            raise NotFoundError("word not found")
        profile = await ProfileRepo(db).get(item.profile_id)
        assert profile is not None
    return await _speak(ctx, profile, item.lemma)
