from fastapi import APIRouter, HTTPException, status
from tutor_contracts import GrammarTopicOut, LanguageOut, LevelOut, ScenarioOut

from tutor_api.curriculum import Curriculum
from tutor_api.routes.deps import Ctx

router = APIRouter(prefix="/curriculum", tags=["curriculum"])


def _check_level(ctx: Ctx, lang: str, level: str | None) -> None:
    if level is not None and not ctx.curriculum(lang).has_level(level):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown level {level!r}")


def _levels(cur: Curriculum) -> list[LevelOut]:
    return [
        LevelOut(
            code=c,
            rank=cur.rank(c),
            label=cur.levels[c].label,
            can_do=cur.levels[c].can_do,
            starter_scenario=cur.levels[c].starter_scenario,
        )
        for c in cur.ordered_levels
    ]


@router.get("/{lang}", response_model=LanguageOut)
async def get_language(lang: str, ctx: Ctx) -> LanguageOut:
    """Language name and levels (with learner-friendly labels), for onboarding screens."""
    cur = ctx.curriculum(lang)
    return LanguageOut(
        code=cur.code,
        name=cur.lang.name,
        native_name=cur.lang.native_name,
        flag=cur.lang.flag,
        levels=_levels(cur),
    )


@router.get("/{lang}/levels", response_model=list[LevelOut])
async def list_levels(lang: str, ctx: Ctx) -> list[LevelOut]:
    return _levels(ctx.curriculum(lang))


@router.get("/{lang}/grammar", response_model=list[GrammarTopicOut])
async def list_grammar(lang: str, ctx: Ctx, level: str | None = None) -> list[GrammarTopicOut]:
    """Topics, optionally only those at exactly `level`."""
    _check_level(ctx, lang, level)
    cur = ctx.curriculum(lang)
    topics = cur.topics_at(level) if level else cur.active_topics()
    return [
        GrammarTopicOut(
            id=t.id,
            level=t.level,
            title=t.title,
            description=t.description,
            prerequisites=list(t.prerequisites),
        )
        for t in sorted(topics, key=lambda t: (cur.rank(t.level), t.id))
    ]


@router.get("/{lang}/scenarios", response_model=list[ScenarioOut])
async def list_scenarios(lang: str, ctx: Ctx, level: str | None = None) -> list[ScenarioOut]:
    """Scenarios at or near `level` (one level either side), or all when omitted."""
    _check_level(ctx, lang, level)
    cur = ctx.curriculum(lang)
    scenarios = (
        cur.scenarios_near(level)
        if level
        else [s for s in cur.scenarios.values() if not s.deprecated]
    )
    return [
        ScenarioOut(id=s.id, level=s.level, title=s.title, setting=s.setting, goals=list(s.goals))
        for s in sorted(scenarios, key=lambda s: (cur.rank(s.level), s.id))
    ]
