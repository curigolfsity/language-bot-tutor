"""daily chat tidy: per-profile switch and the last local day it ran

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-26 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "learner_profiles",
        sa.Column("tidy_chat", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("learner_profiles", sa.Column("last_tidied_on", sa.Date(), nullable=True))
    op.create_index("ix_turns_created_at", "turns", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_turns_created_at", table_name="turns")
    op.drop_column("learner_profiles", "last_tidied_on")
    op.drop_column("learner_profiles", "tidy_chat")
