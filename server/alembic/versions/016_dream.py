"""Dream runs, actions, and cadence state

Revision ID: 016
Revises: 015
Create Date: 2026-08-18

Dream curates memory in the background: superseding contradicted facts, merging
near-duplicates, and distilling recurring signals into patterns. None of it
exists in the OSS core, so all three are built here.

Nothing Dream does is destructive. The memory itself is never deleted or
rewritten - only its lifecycle row changes - and every decision writes an audit
row here with the rationale that produced it. That is what makes the feature
safe to leave switched on: anything it did can be read, explained, and undone.

`dream_actions.reverted_at` rather than deleting the row: a reverted action is
still something Dream did, and losing that record would make the audit trail
lie by omission.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "dream_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        # supersede | merge | synthesis
        sa.Column("kind", sa.String(length=16), nullable=False),
        # running | succeeded | failed | skipped
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        # What the run was over: the entity, the trigger, the memory that started it.
        sa.Column("scope", _jsonb(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("considered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("acted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_dream_runs_project_started", "dream_runs", ["project_id", sa.text("started_at DESC")])
    op.create_index("ix_dream_runs_kind", "dream_runs", ["kind"])

    op.create_table(
        "dream_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("dream_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        # The memory that was acted on.
        sa.Column("subject_memory_id", sa.String(length=255), nullable=False),
        # What it was superseded by / merged into / synthesised as.
        sa.Column("object_memory_id", sa.String(length=255), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        # Why, in the model's own words. An action nobody can explain is one
        # nobody will trust enough to leave enabled.
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dream_actions_run", "dream_actions", ["run_id"])
    op.create_index("ix_dream_actions_project_created", "dream_actions", ["project_id", sa.text("created_at DESC")])
    op.create_index("ix_dream_actions_subject", "dream_actions", ["subject_memory_id"])

    op.create_table(
        "dream_state",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("last_synthesis_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("memory_count_at_last_run", sa.Integer(), nullable=False, server_default="0"),
        # Stamped when synthesis is switched on. Only memories created after it
        # are eligible, so enabling the feature never reprocesses all history.
        sa.Column("enabled_from", sa.DateTime(timezone=True), nullable=True),
        # Hashes of source-id sets already synthesised, so a re-run cannot
        # produce a duplicate pattern.
        sa.Column("pattern_hashes", _jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "entity_type", "entity_id", name="uq_dream_state_entity"),
    )
    op.create_index("ix_dream_state_project", "dream_state", ["project_id"])


def downgrade() -> None:
    op.drop_table("dream_state")
    op.drop_table("dream_actions")
    op.drop_table("dream_runs")
