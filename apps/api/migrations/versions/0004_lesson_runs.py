"""lesson runs: grammar lessons with exercises

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lesson_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.String(length=128), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("exercises", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("llm_model", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["learner_profiles.id"],
            name=op.f("fk_lesson_runs_profile_id_learner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_runs")),
    )
    op.create_index(
        "ix_lesson_runs_profile_created_at",
        "lesson_runs",
        ["profile_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_lesson_runs_profile_created_at", table_name="lesson_runs")
    op.drop_table("lesson_runs")
