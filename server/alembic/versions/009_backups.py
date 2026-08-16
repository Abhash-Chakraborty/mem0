"""Add backups table

Revision ID: 009
Revises: 008
Create Date: 2026-08-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("destination", sa.String(length=512), nullable=False, server_default="local"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_backups_kind", "backups", ["kind"])
    op.create_index("ix_backups_status", "backups", ["status"])
    # The list view is always "newest first", so index the sort column.
    op.create_index("ix_backups_started_at", "backups", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_backups_started_at", table_name="backups")
    op.drop_index("ix_backups_status", table_name="backups")
    op.drop_index("ix_backups_kind", table_name="backups")
    op.drop_table("backups")
