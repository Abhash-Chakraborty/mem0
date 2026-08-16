"""Add channel to webhook_endpoints

Revision ID: 010
Revises: 009
Create Date: 2026-08-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default matters here: existing rows must keep posting the raw
    # signed payload their receivers already parse.
    op.add_column(
        "webhook_endpoints",
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="generic"),
    )


def downgrade() -> None:
    op.drop_column("webhook_endpoints", "channel")
