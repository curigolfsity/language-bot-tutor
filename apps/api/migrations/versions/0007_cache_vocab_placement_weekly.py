"""lesson cache, vocabulary flashcards, placement test, weekly summary

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-25 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lesson_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("topic_id", sa.String(128), nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("native_lang", sa.String(8), nullable=False),
        sa.Column("explanation_language", sa.String(8), nullable=False),
        sa.Column("parts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("llm_model", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("topic_id", "level", "native_lang", "explanation_language"),
    )
    op.create_table(
        "placement_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.Uuid(),
            sa.ForeignKey("learner_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_level", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("vocab_items", sa.Column("box", sa.Integer(), server_default="0", nullable=False))
    op.add_column("vocab_items", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_vocab_items_profile_due_at", "vocab_items", ["profile_id", "due_at"])
    # Words already collected become reviewable right away.
    op.execute("UPDATE vocab_items SET due_at = now()")
    op.add_column("learner_profiles", sa.Column("last_weekly_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("learner_profiles", "last_weekly_on")
    op.drop_index("ix_vocab_items_profile_due_at", table_name="vocab_items")
    op.drop_column("vocab_items", "due_at")
    op.drop_column("vocab_items", "box")
    op.drop_table("placement_runs")
    op.drop_table("lesson_cache")
