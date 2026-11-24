"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-24 15:43:24.028215
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_table('learner_profiles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('target_lang', sa.String(length=8), nullable=False),
    sa.Column('native_lang', sa.String(length=8), nullable=False),
    sa.Column('explanation_lang_override', sa.String(length=8), nullable=True),
    sa.Column('cefr_level', sa.String(length=8), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_learner_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_learner_profiles')),
    sa.UniqueConstraint('user_id', 'target_lang', name=op.f('uq_learner_profiles_user_id_target_lang'))
    )
    op.create_table('user_identities',
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('external_id', sa.String(length=128), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_identities_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('provider', 'external_id', name=op.f('pk_user_identities'))
    )
    op.create_index(op.f('ix_user_identities_user_id'), 'user_identities', ['user_id'], unique=False)
    op.create_table('grammar_mastery',
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('topic_id', sa.String(length=128), nullable=False),
    sa.Column('mastery', sa.Float(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('errors', sa.Integer(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['learner_profiles.id'], name=op.f('fk_grammar_mastery_profile_id_learner_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('profile_id', 'topic_id', name=op.f('pk_grammar_mastery'))
    )
    op.create_table('sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('scenario_id', sa.String(length=128), nullable=True),
    sa.Column('level_at_start', sa.String(length=8), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("mode IN ('free', 'roleplay')", name=op.f('ck_sessions_mode')),
    sa.ForeignKeyConstraint(['profile_id'], ['learner_profiles.id'], name=op.f('fk_sessions_profile_id_learner_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    op.create_index(op.f('ix_sessions_profile_id'), 'sessions', ['profile_id'], unique=False)
    op.create_index('uq_sessions_open_per_profile', 'sessions', ['profile_id'], unique=True, postgresql_where=sa.text('ended_at IS NULL'))
    op.create_table('skill_levels',
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('skill', sa.String(length=16), nullable=False),
    sa.Column('cefr_level', sa.String(length=8), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['learner_profiles.id'], name=op.f('fk_skill_levels_profile_id_learner_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('profile_id', 'skill', name=op.f('pk_skill_levels'))
    )
    op.create_table('vocab_items',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('lemma', sa.String(length=128), nullable=False),
    sa.Column('translation', sa.String(length=256), nullable=False),
    sa.Column('pos', sa.String(length=32), nullable=False),
    sa.Column('seen_count', sa.Integer(), nullable=False),
    sa.Column('mastery', sa.Float(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['learner_profiles.id'], name=op.f('fk_vocab_items_profile_id_learner_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vocab_items')),
    sa.UniqueConstraint('profile_id', 'lemma', name=op.f('uq_vocab_items_profile_id_lemma'))
    )
    op.create_table('turns',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=8), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('grammar_tags', postgresql.ARRAY(sa.Text()), nullable=False),
    sa.Column('llm_model', sa.String(length=64), nullable=True),
    sa.Column('result_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role IN ('learner', 'tutor')", name=op.f('ck_turns_role')),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_turns_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_turns')),
    sa.UniqueConstraint('session_id', 'seq', name=op.f('uq_turns_session_id_seq'))
    )
    op.create_table('mistakes',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('turn_id', sa.BigInteger(), nullable=False),
    sa.Column('wrong', sa.Text(), nullable=False),
    sa.Column('right', sa.Text(), nullable=False),
    sa.Column('rule_tag', sa.String(length=128), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=8), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("severity IN ('minor', 'major')", name=op.f('ck_mistakes_severity')),
    sa.ForeignKeyConstraint(['profile_id'], ['learner_profiles.id'], name=op.f('fk_mistakes_profile_id_learner_profiles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['turn_id'], ['turns.id'], name=op.f('fk_mistakes_turn_id_turns'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mistakes'))
    )
    op.create_index('ix_mistakes_profile_created_at', 'mistakes', ['profile_id', 'created_at'], unique=False)
    op.create_index('ix_mistakes_profile_rule_tag', 'mistakes', ['profile_id', 'rule_tag'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_mistakes_profile_rule_tag', table_name='mistakes')
    op.drop_index('ix_mistakes_profile_created_at', table_name='mistakes')
    op.drop_table('mistakes')
    op.drop_table('turns')
    op.drop_table('vocab_items')
    op.drop_table('skill_levels')
    op.drop_index('uq_sessions_open_per_profile', table_name='sessions', postgresql_where=sa.text('ended_at IS NULL'))
    op.drop_index(op.f('ix_sessions_profile_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_table('grammar_mastery')
    op.drop_index(op.f('ix_user_identities_user_id'), table_name='user_identities')
    op.drop_table('user_identities')
    op.drop_table('learner_profiles')
    op.drop_table('users')
