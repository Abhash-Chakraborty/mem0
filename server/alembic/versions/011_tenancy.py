"""Organizations, projects, memberships and invites

Revision ID: 011
Revises: 010
Create Date: 2026-08-17

Introduces the tenant boundary every later phase scopes to. The tables are new,
so the risky part is not the DDL - it is that an existing instance must keep
working the moment this runs, with every user still able to see every memory
they could see before.

That is handled by seeding a default organization and project and attaching
everything existing to them, in the same transaction as the DDL. A half-applied
tenancy migration would lock the owner out of their own instance.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_ORG_SLUG = "default"
DEFAULT_PROJECT_SLUG = "default-project"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "slug", name="uq_project_org_slug"),
    )
    op.create_index("ix_projects_org_id", "projects", ["org_id"])
    op.create_index("ix_projects_slug", "projects", ["slug"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "project_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])

    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("invited_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invites_org_id", "invites", ["org_id"])
    op.create_index("ix_invites_email", "invites", ["email"])

    op.add_column("api_keys", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_api_keys_project_id", "api_keys", "projects", ["project_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_api_keys_project_id", "api_keys", ["project_id"])

    _seed_default_tenant()


def _seed_default_tenant() -> None:
    """Create the default org/project and attach everything that already exists.

    Runs inside the migration transaction, so an instance is never left with
    tenancy tables but no tenant. Uses raw SQL rather than the ORM models
    because a migration must describe the schema at this revision, not whatever
    models.py happens to look like later.
    """
    conn = op.get_bind()
    dialect = conn.dialect.name
    now = sa.func.now()

    # SQLite (used by the test suite) has no gen_random_uuid().
    if dialect == "postgresql":
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        new_uuid = "gen_random_uuid()"
    else:
        new_uuid = "lower(hex(randomblob(16)))"

    org_id = conn.execute(
        sa.text(
            f"""
            INSERT INTO organizations (id, name, slug, created_at, updated_at)
            VALUES ({new_uuid}, :name, :slug, :now, :now)
            RETURNING id
            """
        ),
        {"name": "Default", "slug": DEFAULT_ORG_SLUG, "now": _now(conn)},
    ).scalar_one()

    project_id = conn.execute(
        sa.text(
            f"""
            INSERT INTO projects (id, org_id, name, slug, description, settings, created_at, updated_at)
            VALUES ({new_uuid}, :org_id, :name, :slug, '', '{{}}', :now, :now)
            RETURNING id
            """
        ),
        {
            "org_id": org_id,
            "name": "default-project",
            "slug": DEFAULT_PROJECT_SLUG,
            "now": _now(conn),
        },
    ).scalar_one()

    # Existing admins become owners; everyone else a member. Without this the
    # only account on the instance would have no membership and, once the
    # scope dependency lands, no access to anything.
    conn.execute(
        sa.text(
            f"""
            INSERT INTO memberships (id, org_id, user_id, role, created_at)
            SELECT {new_uuid}, :org_id, id,
                   CASE WHEN role = 'admin' THEN 'owner' ELSE 'member' END,
                   :now
            FROM users
            """
        ),
        {"org_id": org_id, "now": _now(conn)},
    )

    conn.execute(
        sa.text("UPDATE api_keys SET project_id = :project_id WHERE project_id IS NULL"),
        {"project_id": project_id},
    )

    _ = now  # kept for readability of the intent above


def _now(conn):
    """Current UTC timestamp, as a Python value.

    Passed as a bound parameter rather than using the database's now() so the
    seeded rows share one timestamp and the code reads the same on SQLite and
    Postgres.
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def downgrade() -> None:
    op.drop_index("ix_api_keys_project_id", table_name="api_keys")
    op.drop_constraint("fk_api_keys_project_id", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "project_id")

    op.drop_table("invites")
    op.drop_table("project_members")
    op.drop_table("memberships")
    op.drop_table("projects")
    op.drop_table("organizations")
