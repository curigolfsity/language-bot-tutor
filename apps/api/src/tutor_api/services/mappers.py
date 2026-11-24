"""DB model -> contract DTO. DB models never leave apps/api."""

from __future__ import annotations

from collections.abc import Sequence

from tutor_contracts import LearnerProfileOut, MistakeOut, SessionOut, SkillLevelOut, VocabOut

from tutor_api.curriculum import Curriculum
from tutor_api.db.models import LearnerProfile, Mistake, Session, SkillLevel, VocabItem


def profile_out(p: LearnerProfile, skills: Sequence[SkillLevel]) -> LearnerProfileOut:
    return LearnerProfileOut(
        id=p.id,
        user_id=p.user_id,
        target_lang=p.target_lang,
        native_lang=p.native_lang,
        cefr_level=p.cefr_level,
        explanation_lang_override=p.explanation_lang_override,  # type: ignore[arg-type]
        skills=[
            SkillLevelOut(skill=s.skill, cefr_level=s.cefr_level, score=s.score)  # type: ignore[arg-type]
            for s in skills
        ],
        created_at=p.created_at,
    )


def topic_title(curriculum: Curriculum, topic_id: str) -> str | None:
    topic = curriculum.topics.get(topic_id)
    return topic.title if topic else None


def mistake_out(m: Mistake, curriculum: Curriculum) -> MistakeOut:
    return MistakeOut(
        id=m.id,
        wrong=m.wrong,
        right=m.right,
        rule_tag=m.rule_tag,
        rule_title=topic_title(curriculum, m.rule_tag),
        explanation=m.explanation,
        severity=m.severity,  # type: ignore[arg-type]
        created_at=m.created_at,
    )


def vocab_out(v: VocabItem) -> VocabOut:
    return VocabOut(
        lemma=v.lemma,
        translation=v.translation,
        pos=v.pos,
        seen_count=v.seen_count,
        mastery=v.mastery,
        last_seen_at=v.last_seen_at,
    )


def session_out(
    s: Session, opening_line: str, curriculum: Curriculum, opening_turn_id: int | None = None
) -> SessionOut:
    scenario = curriculum.scenarios.get(s.scenario_id) if s.scenario_id else None
    return SessionOut(
        id=s.id,
        profile_id=s.profile_id,
        mode=s.mode,  # type: ignore[arg-type]
        scenario_id=s.scenario_id,
        scenario_title=scenario.title if scenario else None,
        level_at_start=s.level_at_start,
        started_at=s.started_at,
        ended_at=s.ended_at,
        opening_line=opening_line,
        opening_turn_id=opening_turn_id,
    )
