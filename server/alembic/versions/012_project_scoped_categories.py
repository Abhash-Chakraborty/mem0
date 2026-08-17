"""Scope categories to a project

Revision ID: 012
Revises: 011
Create Date: 2026-08-18

Categories were instance-wide. Once projects exist that is wrong in a way that
shows up immediately: two projects with different subject matter want different
taxonomies, and a category list that mixes them is useless to both.

The delicate part is the uniqueness constraint. `categories.name` was globally
unique; it becomes unique per project, so two projects can each have a
"Preferences" category. Dropping the old constraint before adding the new one
matters - Postgres will not let the pair coexist.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("project_id", sa.Uuid(), nullable=True))

    # Every existing category belongs to the default project, for the same
    # reason every existing memory does: it is where they were all created.
    op.execute(
        """
        UPDATE categories
        SET project_id = (
            SELECT p.id FROM projects p
            JOIN organizations o ON o.id = p.org_id
            ORDER BY (p.slug = 'default-project') DESC, p.created_at
            LIMIT 1
        )
        WHERE project_id IS NULL
        """
    )

    op.create_foreign_key(
        "fk_categories_project_id", "categories", "projects", ["project_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_categories_project_id", "categories", ["project_id"])

    # The global unique index on `name` is what actually blocks two projects
    # from sharing a category name, so it has to go before the scoped one lands.
    _drop_name_unique()
    op.create_index("uq_category_project_name", "categories", ["project_id", "name"], unique=True)


def _drop_name_unique() -> None:
    """Remove the old global uniqueness on `categories.name`.

    SQLAlchemy renders `unique=True, index=True` as a unique *index* on
    Postgres but some histories end up with a *constraint* instead, and the two
    are dropped by different statements. Both are attempted and neither is
    required to exist, so this works against either shape.
    """
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_categories_name"))
    conn.execute(sa.text("ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_name_key"))
    conn.execute(sa.text("ALTER TABLE categories DROP CONSTRAINT IF EXISTS uq_categories_name"))


def downgrade() -> None:
    op.drop_index("uq_category_project_name", table_name="categories")

    # Going back to a global unique name can fail on real data - two projects
    # may each hold a "Preferences". Duplicates are folded into the oldest row
    # rather than letting the migration die halfway.
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text(
                """
                DELETE FROM categories c
                USING categories keep
                WHERE c.name = keep.name AND c.created_at > keep.created_at
                """
            )
        )
        conn.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_categories_name ON categories (name)"))

    op.drop_index("ix_categories_project_id", table_name="categories")
    op.drop_constraint("fk_categories_project_id", "categories", type_="foreignkey")
    op.drop_column("categories", "project_id")
