"""llm calls: usage of non-turn model calls

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls")
    op.drop_table("llm_calls")
