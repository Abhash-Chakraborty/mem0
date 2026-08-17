"""Materialized graph nodes and edges

Revision ID: 017
Revises: 016
Create Date: 2026-08-18

The graph endpoint re-derived every node and edge on each request by scanning
the entity store. That is correct and it is the slowest page in the app: the
work is O(memories x entities-per-memory) and none of it changes between two
requests a second apart.

These tables hold the derived result. They are a cache, and they are treated
like one - a full rebuild is always available, and a stale graph is a
performance problem rather than a correctness one, because the source of truth
is still the entity store.

`entity_key` rather than a surrogate id: the key is `type:id`, which is already
unique and already what the client uses, so a join table would add a lookup
without adding information.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("entity_key", sa.String(length=320), primary_key=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("memory_count", sa.Integer(), nullable=False, server_default="0"),
        # Denormalised so the min_degree filter is a column predicate rather
        # than a join and a group-by on every request.
        sa.Column("degree", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_graph_nodes_project_degree", "graph_nodes", ["project_id", "degree"])
    op.create_index("ix_graph_nodes_label", "graph_nodes", ["project_id", "label"])

    op.create_table(
        "graph_edges",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_key", sa.String(length=320), primary_key=True),
        sa.Column("target_key", sa.String(length=320), primary_key=True),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Both directions are indexed because neighbourhood expansion asks "edges
    # touching this key" and an edge is stored once, source-first.
    op.create_index("ix_graph_edges_source", "graph_edges", ["project_id", "source_key"])
    op.create_index("ix_graph_edges_target", "graph_edges", ["project_id", "target_key"])
    op.create_index("ix_graph_edges_weight", "graph_edges", ["project_id", "weight"])


def downgrade() -> None:
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
