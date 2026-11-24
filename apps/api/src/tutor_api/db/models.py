"""SQLAlchemy 2 models. These never leave `apps/api` (map to tutor_contracts DTOs instead).

Curriculum ids (topic_id, rule_tag, scenario_id, grammar_tags) are stored as text with no FK:
the YAML is the authority and is validated at startup.

Postgres-specific types have SQLite variants only so the test suite can run in-memory.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TextArray = ARRAY(Text).with_variant(JSON(), "sqlite")
JsonB = JSONB().with_variant(JSON(), "sqlite")
# SQLite only auto-increments INTEGER PRIMARY KEY.
BigId = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserIdentity(Base):
    __tablename__ = "user_identities"
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )


class LearnerProfile(Base):
    __tablename__ = "learner_profiles"
    __table_args__ = (UniqueConstraint("user_id", "target_lang"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    target_lang: Mapped[str] = mapped_column(String(8))
    native_lang: Mapped[str] = mapped_column(String(8))
    explanation_lang_override: Mapped[str | None] = mapped_column(String(8), nullable=True)
    cefr_level: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SkillLevel(Base):
    __tablename__ = "skill_levels"
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learner_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    skill: Mapped[str] = mapped_column(String(16), primary_key=True)
    cefr_level: Mapped[str] = mapped_column(String(8))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GrammarMastery(Base):
    __tablename__ = "grammar_mastery"
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learner_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    mastery: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VocabItem(Base):
    __tablename__ = "vocab_items"
    __table_args__ = (UniqueConstraint("profile_id", "lemma"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learner_profiles.id", ondelete="CASCADE")
    )
    lemma: Mapped[str] = mapped_column(String(128))
    translation: Mapped[str] = mapped_column(String(256), default="")
    pos: Mapped[str] = mapped_column(String(32), default="")
    seen_count: Mapped[int] = mapped_column(Integer, default=0)
    mastery: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("mode IN ('free', 'roleplay')", name="mode"),
        # At most one open session per profile.
        Index(
            "uq_sessions_open_per_profile",
            "profile_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learner_profiles.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(16))
    scenario_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level_at_start: Mapped[str] = mapped_column(String(8))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        CheckConstraint("role IN ('learner', 'tutor')", name="role"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    grammar_tags: Mapped[list[str]] = mapped_column(TextArray, default=list)
    llm_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Mistake(Base):
    __tablename__ = "mistakes"
    __table_args__ = (
        CheckConstraint("severity IN ('minor', 'major')", name="severity"),
        Index("ix_mistakes_profile_rule_tag", "profile_id", "rule_tag"),
        Index("ix_mistakes_profile_created_at", "profile_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learner_profiles.id", ondelete="CASCADE")
    )
    turn_id: Mapped[int] = mapped_column(BigId, ForeignKey("turns.id", ondelete="CASCADE"))
    wrong: Mapped[str] = mapped_column(Text)
    right: Mapped[str] = mapped_column(Text)
    rule_tag: Mapped[str] = mapped_column(String(128))
    explanation: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
