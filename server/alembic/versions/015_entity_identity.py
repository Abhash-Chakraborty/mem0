"""Entity aliases and profiles

Revision ID: 015
Revises: 014
Create Date: 2026-08-18

One person arriving from Telegram, the website and Discord becomes three
entities, and their memories fragment across all three. An alias row makes two
identifiers the same entity, so a search under any of them sees the whole
person.

The unique constraint on (project_id, entity_type, alias_id) is the load-bearing
part of this schema: without it an identifier could point at two canonicals and
resolution would be ambiguous, with no way to say which answer is right. Chains
are collapsed at write time (see identity.py), so resolution is always one hop
and can never cycle.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        # The identifier that survives. Everything else resolves to this.
        sa.Column("canonical_id", sa.String(length=255), nullable=False),
        sa.Column("alias_id", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # An alias may point at exactly one canonical. Without this, resolution
        # has two answers and no way to choose.
        sa.UniqueConstraint("project_id", "entity_type", "alias_id", name="uq_entity_alias"),
    )
    op.create_index("ix_entity_aliases_canonical", "entity_aliases", ["project_id", "entity_type", "canonical_id"])
    op.create_index("ix_entity_aliases_project", "entity_aliases", ["project_id"])

    op.create_table(
        "entity_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "entity_type", "entity_id", name="uq_entity_profile"),
    )
    op.create_index("ix_entity_profiles_project", "entity_profiles", ["project_id"])


def downgrade() -> None:
    op.drop_table("entity_profiles")
    op.drop_table("entity_aliases")
