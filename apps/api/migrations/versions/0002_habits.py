"""habits: streaks, daily goal, reminders

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("learner_profiles", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column("learner_profiles", sa.Column("daily_goal", sa.Integer(), nullable=True))
    op.add_column(
        "learner_profiles",
        sa.Column("reminders_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("learner_profiles", sa.Column("last_reminded_on", sa.Date(), nullable=True))
    op.add_column(
        "learner_profiles",
        sa.Column("streak_best", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_learner_profiles_daily_goal_range"),
        "learner_profiles",
        "daily_goal IS NULL OR (daily_goal BETWEEN 1 AND 200)",
    )
    op.create_table(
        "daily_activity",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("messages", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["learner_profiles.id"],
            name=op.f("fk_daily_activity_profile_id_learner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", "day", name=op.f("pk_daily_activity")),
    )


def downgrade() -> None:
    op.drop_table("daily_activity")
    op.drop_constraint(
        op.f("ck_learner_profiles_daily_goal_range"), "learner_profiles", type_="check"
    )
    for col in ("streak_best", "last_reminded_on", "reminders_enabled", "daily_goal", "timezone"):
        op.drop_column("learner_profiles", col)
