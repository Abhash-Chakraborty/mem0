"""Memory lifecycle, access, and feedback

Revision ID: 014
Revises: 013
Create Date: 2026-08-18

Dream (phase 07) and decay (phase 08) both need somewhere to record what
happened to a memory and how often it has been used. Neither exists in the OSS
core - `decay=True` raises, and supersede/merge live only in the hosted client -
so the state has to be ours.

Every table keys on the SDK's memory id as a plain string, with no foreign key
to it. The memories live in pgvector under the SDK's schema; a foreign key into
a table this app does not own would break the next time the SDK changed it. The
cost is that deletes have to cascade in application code, which
lifecycle_services.forget() does.

Rows are created lazily: a memory with no lifecycle row is active, and one with
no access row has never been read. That keeps these tables proportional to
activity rather than to memory count, and makes the whole layer safe to add to
an existing install with no backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "memory_lifecycle",
        # The SDK's memory id. A string, not a UUID column: the id format is
        # the SDK's to change, and a type mismatch here would be a migration.
        sa.Column("memory_id", sa.String(length=255), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("superseded_by", sa.String(length=255), nullable=True),
        sa.Column("merged_into", sa.String(length=255), nullable=True),
        # Why, in one sentence. Dream decisions are only trustworthy if they
        # are legible after the fact.
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=24), nullable=False, server_default="system"),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_lifecycle_project", "memory_lifecycle", ["project_id"])
    op.create_index("ix_memory_lifecycle_state", "memory_lifecycle", ["project_id", "state"])
    op.create_index("ix_memory_lifecycle_superseded_by", "memory_lifecycle", ["superseded_by"])

    op.create_table(
        "memory_access",
        sa.Column("memory_id", sa.String(length=255), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_access_at", sa.DateTime(timezone=True), nullable=True),
        # Last 20 timestamps, bounded. Enough to see a usage shape without the
        # row growing without limit on a hot memory.
        sa.Column("recent", _jsonb(), nullable=True),
    )
    op.create_index("ix_memory_access_project", "memory_access", ["project_id"])
    op.create_index("ix_memory_access_last", "memory_access", ["project_id", "last_access_at"])

    op.create_table(
        "memory_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("memory_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reasons", _jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_feedback_memory", "memory_feedback", ["memory_id"])
    op.create_index("ix_memory_feedback_project", "memory_feedback", ["project_id"])

    op.create_table(
        "pattern_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pattern_memory_id", sa.String(length=255), nullable=False),
        sa.Column("source_memory_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("pattern_memory_id", "source_memory_id", name="uq_pattern_source"),
    )
    op.create_index("ix_pattern_sources_pattern", "pattern_sources", ["pattern_memory_id"])
    op.create_index("ix_pattern_sources_source", "pattern_sources", ["source_memory_id"])


def downgrade() -> None:
    op.drop_table("pattern_sources")
    op.drop_table("memory_feedback")
    op.drop_table("memory_access")
    op.drop_table("memory_lifecycle")
