"""HTTP client for the core API. The bot's only dependency on the backend."""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, TypeAdapter
from tutor_contracts import (
    AskOut,
    AskRequest,
    CreateSessionRequest,
    DailyProgressOut,
    HelpKind,
    HelpOut,
    HelpRequest,
    LanguageOut,
    LearnerPatch,
    LearnerProfileOut,
    LessonAnswerOut,
    LessonAnswerRequest,
    LessonOut,
    LessonSuggestionsOut,
    LevelOut,
    MistakeOut,
    PlacementAnswerRequest,
    PlacementStepOut,
    PracticeItemOut,
    ReminderClaimRequest,
    ReminderOut,
    ResolveUserRequest,
    ResolveUserResponse,
    ReviewAnswerOut,
    ReviewAnswerRequest,
    ReviewQueueOut,
    SavedWordsOut,
    SaveWordsRequest,
    ScenarioOut,
    SessionOut,
    SessionSummary,
    StartLessonRequest,
    TurnRequest,
    TurnResponse,
    VocabOut,
    WeeklySummaryOut,
    WordAnswerOut,
    WordAnswerRequest,
    WordQueueOut,
)

T = TypeVar("T")


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class NotFound(ApiError):
    pass


class TutorApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 180.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url, headers={"X-Client-Key": api_key}, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        out: type[T] | Any,
        body: BaseModel | None = None,
        **params: Any,
    ) -> T:
        json = body.model_dump(mode="json", exclude_unset=True) if body is not None else None
        clean_params = {k: v for k, v in params.items() if v is not None}
        resp = await self._http.request(method, url, json=json, params=clean_params or None)
        return self._parse(resp, out)

    @staticmethod
    def _parse(resp: httpx.Response, out: type[T] | Any) -> T:
        if resp.status_code >= 400:
            try:
                detail = str(resp.json().get("detail", resp.text))
            except ValueError:
                detail = resp.text
            cls = NotFound if resp.status_code == 404 else ApiError
            raise cls(resp.status_code, detail)
        return TypeAdapter(out).validate_python(resp.json())

    async def _audio(self, url: str) -> tuple[bytes, str]:
        resp = await self._http.get(url)
        if resp.status_code >= 400:
            self._parse(resp, object)
        return resp.content, resp.headers.get("content-type", "audio/ogg")

    async def turn_speech(self, turn_id: int) -> tuple[bytes, str]:
        """The tutor message read aloud: (audio bytes, mime type)."""
        return await self._audio(f"/v1/turns/{turn_id}/speech")

    async def word_speech(self, word_id: int) -> tuple[bytes, str]:
        return await self._audio(f"/v1/words/{word_id}/speech")

    async def save_words(
        self, profile_id: UUID, text: str, turn_id: int | None = None
    ) -> SavedWordsOut:
        req = SaveWordsRequest(text=text, turn_id=turn_id)
        return await self._request("POST", f"/v1/learners/{profile_id}/words", SavedWordsOut, req)

    async def practice_next(self, profile_id: UUID) -> PracticeItemOut:
        return await self._request(
            "GET", f"/v1/learners/{profile_id}/practice/next", PracticeItemOut
        )

    async def next_word(self, profile_id: UUID) -> WordQueueOut:
        return await self._request("GET", f"/v1/learners/{profile_id}/words/next", WordQueueOut)

    async def answer_word(self, word_id: int, knew: bool) -> WordAnswerOut:
        req = WordAnswerRequest(knew=knew)
        return await self._request("POST", f"/v1/words/{word_id}/answer", WordAnswerOut, req)

    async def start_placement(self, profile_id: UUID) -> PlacementStepOut:
        return await self._request("POST", f"/v1/learners/{profile_id}/placement", PlacementStepOut)

    async def answer_placement(
        self, run_id: int, question_id: str, choice: int
    ) -> PlacementStepOut:
        req = PlacementAnswerRequest(question_id=question_id, choice=choice)
        return await self._request("POST", f"/v1/placement/{run_id}/answer", PlacementStepOut, req)

    async def weekly(self, profile_id: UUID) -> WeeklySummaryOut:
        return await self._request("GET", f"/v1/learners/{profile_id}/weekly", WeeklySummaryOut)

    async def claim_weekly(self, provider: str, target_lang: str) -> list[WeeklySummaryOut]:
        req = ReminderClaimRequest(provider=provider, target_lang=target_lang)
        return await self._request(
            "POST", "/v1/reminders/weekly/claim", list[WeeklySummaryOut], req
        )

    async def resolve_user(self, req: ResolveUserRequest) -> ResolveUserResponse:
        return await self._request("POST", "/v1/users/resolve", ResolveUserResponse, req)

    async def get_learner(self, profile_id: UUID) -> LearnerProfileOut:
        return await self._request("GET", f"/v1/learners/{profile_id}", LearnerProfileOut)

    async def vocab(self, profile_id: UUID, limit: int = 500) -> list[VocabOut]:
        return await self._request(
            "GET", f"/v1/learners/{profile_id}/vocab", list[VocabOut], limit=limit
        )

    async def language(self, lang: str) -> LanguageOut:
        return await self._request("GET", f"/v1/curriculum/{lang}", LanguageOut)

    async def help(self, turn_id: int, kind: HelpKind) -> HelpOut:
        return await self._request(
            "POST", f"/v1/turns/{turn_id}/help", HelpOut, HelpRequest(kind=kind)
        )

    async def patch_learner(self, profile_id: UUID, patch: LearnerPatch) -> LearnerProfileOut:
        return await self._request("PATCH", f"/v1/learners/{profile_id}", LearnerProfileOut, patch)

    async def progress(self, profile_id: UUID) -> DailyProgressOut:
        return await self._request("GET", f"/v1/learners/{profile_id}/progress", DailyProgressOut)

    async def claim_reminders(self, provider: str, target_lang: str) -> list[ReminderOut]:
        req = ReminderClaimRequest(provider=provider, target_lang=target_lang)
        return await self._request("POST", "/v1/reminders/claim", list[ReminderOut], req)

    async def ask(self, profile_id: UUID, question: str, turn_id: int | None = None) -> AskOut:
        req = AskRequest(question=question, turn_id=turn_id)
        return await self._request("POST", f"/v1/learners/{profile_id}/ask", AskOut, req)

    async def lessons(self, profile_id: UUID) -> LessonSuggestionsOut:
        return await self._request(
            "GET", f"/v1/learners/{profile_id}/lessons", LessonSuggestionsOut
        )

    async def start_lesson(self, profile_id: UUID, topic_id: str, fresh: bool = False) -> LessonOut:
        req = StartLessonRequest(topic_id=topic_id, fresh=fresh)
        return await self._request("POST", f"/v1/learners/{profile_id}/lessons", LessonOut, req)

    async def answer_lesson(self, lesson_id: int, index: int, answer: str) -> LessonAnswerOut:
        req = LessonAnswerRequest(index=index, answer=answer)
        return await self._request("POST", f"/v1/lessons/{lesson_id}/answer", LessonAnswerOut, req)

    async def next_review(self, profile_id: UUID) -> ReviewQueueOut:
        return await self._request("GET", f"/v1/learners/{profile_id}/review/next", ReviewQueueOut)

    async def answer_review(self, card_id: int, answer: str) -> ReviewAnswerOut:
        return await self._request(
            "POST",
            f"/v1/review/{card_id}/answer",
            ReviewAnswerOut,
            ReviewAnswerRequest(answer=answer),
        )

    async def mistakes(self, profile_id: UUID, limit: int = 10) -> list[MistakeOut]:
        return await self._request(
            "GET", f"/v1/learners/{profile_id}/mistakes", list[MistakeOut], limit=limit
        )

    async def active_session(self, profile_id: UUID) -> SessionOut | None:
        try:
            return await self._request(
                "GET", f"/v1/learners/{profile_id}/active-session", SessionOut
            )
        except NotFound:
            return None

    async def levels(self, lang: str) -> list[LevelOut]:
        return await self._request("GET", f"/v1/curriculum/{lang}/levels", list[LevelOut])

    async def scenarios(self, lang: str, level: str | None = None) -> list[ScenarioOut]:
        return await self._request(
            "GET", f"/v1/curriculum/{lang}/scenarios", list[ScenarioOut], level=level
        )

    async def start_session(self, profile_id: UUID, scenario_id: str | None = None) -> SessionOut:
        req = CreateSessionRequest(profile_id=profile_id, scenario_id=scenario_id)
        return await self._request("POST", "/v1/sessions", SessionOut, req)

    async def send_turn(self, session_id: UUID, text: str) -> TurnResponse:
        return await self._request(
            "POST", f"/v1/sessions/{session_id}/turns", TurnResponse, TurnRequest(text=text)
        )

    async def send_voice_turn(
        self, session_id: UUID, audio: bytes, filename: str, mime_type: str
    ) -> TurnResponse:
        resp = await self._http.post(
            f"/v1/sessions/{session_id}/turns/voice",
            files={"audio": (filename, audio, mime_type)},
        )
        return self._parse(resp, TurnResponse)

    async def end_session(self, session_id: UUID) -> SessionSummary:
        return await self._request("POST", f"/v1/sessions/{session_id}/end", SessionSummary)
