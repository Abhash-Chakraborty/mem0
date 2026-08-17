"""Full request traces

Revision ID: 013
Revises: 012
Create Date: 2026-08-18

request_logs held six columns: method, path, status, latency, auth type, time.
The Requests page needs to answer what kind of call it was, who it was about,
how many memories it touched, what went in and what came out. None of that is
derivable from a path, so it gets stored.

This makes a narrow log table into the widest table in the database, which is
why the retention sweep lands in the same phase rather than "later". A trace
table with no expiry is a disk-space incident with a delay fuse.

Every column is nullable with no backfill: existing rows describe requests whose
bodies were never captured, and inventing values for them would make the log
lie about its own history.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb():
    """JSONB on Postgres, JSON elsewhere, so the test suite can run on SQLite."""
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column("request_logs", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.add_column("request_logs", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.add_column("request_logs", sa.Column("request_type", sa.String(length=24), nullable=True))
    op.add_column("request_logs", sa.Column("entities", _jsonb(), nullable=True))
    op.add_column("request_logs", sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("request_logs", sa.Column("payload", _jsonb(), nullable=True))
    op.add_column("request_logs", sa.Column("result_summary", _jsonb(), nullable=True))
    op.add_column("request_logs", sa.Column("memory_ids", _jsonb(), nullable=True))
    op.add_column(
        "request_logs", sa.Column("is_playground", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("request_logs", sa.Column("error", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_request_logs_project_id", "request_logs", "projects", ["project_id"], ["id"], ondelete="CASCADE"
    )

    # (project, time desc) is the shape of every list query the page makes, so
    # it is one composite index rather than two single-column ones the planner
    # would have to combine.
    op.create_index(
        "ix_request_logs_project_created",
        "request_logs",
        ["project_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_request_logs_request_type", "request_logs", ["request_type"])
    op.create_index("ix_request_logs_request_id", "request_logs", ["request_id"])

    # GIN over the entities array answers "everything about alice" directly.
    # Without it that filter is a sequential scan over the largest table here.
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "ix_request_logs_entities",
            "request_logs",
            ["entities"],
            postgresql_using="gin",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_request_logs_entities", table_name="request_logs")

    op.drop_index("ix_request_logs_request_id", table_name="request_logs")
    op.drop_index("ix_request_logs_request_type", table_name="request_logs")
    op.drop_index("ix_request_logs_project_created", table_name="request_logs")
    op.drop_constraint("fk_request_logs_project_id", "request_logs", type_="foreignkey")

    for column in (
        "error",
        "is_playground",
        "memory_ids",
        "result_summary",
        "payload",
        "event_count",
        "entities",
        "request_type",
        "request_id",
        "project_id",
    ):
        op.drop_column("request_logs", column)
