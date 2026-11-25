"""review items: spaced repetition of learner mistakes

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("wrong", sa.Text(), nullable=False),
        sa.Column("right", sa.Text(), nullable=False),
        sa.Column("rule_tag", sa.String(length=128), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("box", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviews", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["learner_profiles.id"],
            name=op.f("fk_review_items_profile_id_learner_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_items")),
        sa.UniqueConstraint(
            "profile_id", "wrong", "right", name=op.f("uq_review_items_profile_id_wrong_right")
        ),
    )
    op.create_index(
        "ix_review_items_profile_due_at", "review_items", ["profile_id", "due_at"], unique=False
    )
    # Cards for mistakes made before this feature existed (latest occurrence of each), due now.
    op.execute(
        """
        INSERT INTO review_items (profile_id, source_text, wrong, "right", rule_tag, explanation,
                                  box, due_at, reviews, lapses, created_at)
        SELECT DISTINCT ON (m.profile_id, m.wrong, m."right")
               m.profile_id, t.text, m.wrong, m."right", m.rule_tag, m.explanation,
               0, now(), 0, 0, m.created_at
        FROM mistakes m JOIN turns t ON t.id = m.turn_id
        ORDER BY m.profile_id, m.wrong, m."right", m.created_at DESC
        """
    )


def downgrade() -> None:
    op.drop_index("ix_review_items_profile_due_at", table_name="review_items")
    op.drop_table("review_items")
