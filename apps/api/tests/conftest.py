from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from tutor_api.config import REPO_ROOT, Settings
from tutor_api.curriculum import Curriculum, load_curriculum
from tutor_api.db import Base, make_engine, make_sessionmaker
from tutor_api.llm import LLMHelpOutcome, LLMTurnOutcome
from tutor_api.main import create_app
from tutor_api.services.context import AppContext
from tutor_contracts import Correction, NewVocab, TurnResult

API_KEY = "test-key"


@pytest.fixture(scope="session")
def es() -> Curriculum:
    return load_curriculum(REPO_ROOT / "curriculum" / "es")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        DATABASE_URL="sqlite+aiosqlite://",
        CLIENT_API_KEYS=API_KEY,
        TUTOR_MODEL="test-model",
        CURRICULUM_DIR=str(REPO_ROOT / "curriculum"),
    )


class FakeLLM:
    """Stands in for AnthropicTurnLLM. Returns queued outcomes and records the prompts."""

    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.queue: list[LLMTurnOutcome | Exception] = []
        self.help_calls: list[tuple[str, str]] = []
        self.help_refuse = False

    def push_result(self, result: TurnResult) -> None:
        self.queue.append(
            LLMTurnOutcome(
                result=result,
                refused=False,
                refusal_category=None,
                model=self.model,
                stop_reason="end_turn",
                input_tokens=100,
                output_tokens=50,
            )
        )

    def push_refusal(self) -> None:
        self.queue.append(
            LLMTurnOutcome(
                result=None,
                refused=True,
                refusal_category="other",
                model=self.model,
                stop_reason="refusal",
                input_tokens=100,
                output_tokens=0,
            )
        )

    async def generate_help(self, system_prompt: str, user_content: str) -> LLMHelpOutcome:
        self.help_calls.append((system_prompt, user_content))
        if self.help_refuse:
            return LLMHelpOutcome(None, True, self.model, 10, 0)
        return LLMHelpOutcome("help text", False, self.model, 10, 5)

    async def generate_turn(self, system_prompt: str, user_content: str) -> LLMTurnOutcome:
        self.calls.append((system_prompt, user_content))
        item = self.queue.pop(0) if self.queue else None
        if isinstance(item, Exception):
            raise item
        if item is None:
            self.push_result(
                TurnResult(reply="¡Genial!", corrections=[], new_vocab=[], grammar_tags=[])
            )
            item = self.queue.pop(0)
        return item  # type: ignore[return-value]


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
async def ctx(settings: Settings, es: Curriculum, fake_llm: FakeLLM) -> AsyncIterator[AppContext]:
    engine = make_engine(
        settings.database_url, poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield AppContext(
        settings=settings,
        curricula={"es": es},
        sessionmaker=make_sessionmaker(engine),
        llm=fake_llm,
    )
    await engine.dispose()


@pytest.fixture
async def client(ctx: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(ctx)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Client-Key": API_KEY}
    ) as c:
        yield c


def make_result(
    reply: str = "¡Qué bien!",
    corrections: list[tuple[str, str, str, str]] | None = None,
    tags: list[str] | None = None,
    vocab: list[str] | None = None,
) -> TurnResult:
    return TurnResult(
        reply=reply,
        corrections=[
            Correction(wrong=w, right=r, rule_tag=t, explanation="x", severity=s)  # type: ignore[arg-type]
            for w, r, t, s in (corrections or [])
        ],
        new_vocab=[
            NewVocab(lemma=v, translation="t", pos="noun", example="e") for v in vocab or []
        ],
        grammar_tags=tags or [],
    )


@pytest.fixture
def result_factory() -> Callable[..., TurnResult]:
    return make_result


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root
