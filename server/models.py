import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Organization(Base):
    """Top-level tenant. Owns projects, members, and everything under them.

    Self-hosted instances will usually have exactly one, created by the
    migration. The model exists anyway because project scoping needs somewhere
    to hang membership, and retrofitting a tenant boundary later is far more
    expensive than carrying an unused one.
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class Project(Base):
    """A memory namespace inside an organization.

    `settings` holds per-project configuration that has no reason to be its own
    column - custom instructions, category behaviour, retention and Dream
    thresholds - so tuning any of them is a JSON write rather than a migration.
    """

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_project_org_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class Membership(Base):
    """A user's role within an organization.

    Roles are ordered owner > admin > member > reader and compared by rank, not
    by equality, so a new role can be slotted in without rewriting every check.
    """

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ProjectMember(Base):
    """Optional narrowing of an org membership to specific projects.

    Absent rows mean "this user's org role applies to every project", which is
    the common case. A row only exists to restrict, never to grant more than the
    org role already allows.
    """

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Invite(Base):
    """A pending invitation to join an organization.

    Only the hash of the token is stored, for the same reason API keys store
    only their hash: a leaked database must not hand out working invitations.
    """

    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    token_hash: Mapped[str] = mapped_column(Text)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    key_prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(255))
    # Which project this key may read and write. Nullable so keys minted before
    # tenancy existed keep working; they resolve to the default project.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RequestLog(Base):
    """One HTTP exchange, with enough of it kept to explain what happened.

    The trace columns are all nullable and none are backfilled: rows written
    before migration 013 describe requests whose bodies were never captured,
    and inventing values for them would make the log lie about its own history.
    """

    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(512))
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    auth_type: Mapped[str] = mapped_column(String(32), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Matches the X-Request-ID header, so a log line and a trace row can be
    # tied together without guessing from a timestamp.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    request_type: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    # [{"type": "user", "id": "alice"}] rather than three nullable columns, so
    # the Entities column renders uniformly and one GIN index serves them all.
    entities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    memory_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_playground: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RefreshTokenJti(Base):
    __tablename__ = "refresh_token_jtis"

    jti: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Settings(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class Category(Base):
    """A label applied to memories, scoped to one project.

    Names are unique per project, not per instance: two projects with different
    subject matter will both reasonably want a "Preferences" category, and
    forcing them to share one taxonomy makes the list useless to both.
    """

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_category_project_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(32), default="#7c3aed")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # When True, this category is attached to every new memory automatically
    # (no AI judgment), independent of the AI auto-classifier. Defaults off.
    auto_add: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class MemoryCategory(Base):
    __tablename__ = "memory_categories"
    __table_args__ = (UniqueConstraint("memory_id", "category_id", name="uq_memory_category"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    memory_id: Mapped[str] = mapped_column(String(255), index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(24), default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class MemoryLifecycle(Base):
    """What has happened to a memory beyond existing.

    Rows are lazy: no row means active. That keeps the table proportional to
    how much has actually happened rather than to how many memories exist, and
    means this layer can be added to a full instance with no backfill.

    `memory_id` is the SDK's id as a plain string with no foreign key. The
    memories live in pgvector under the SDK's schema; a foreign key into a
    table this app does not own would break the next time the SDK changed it.
    Deletes cascade in application code instead - see lifecycle_services.forget.
    """

    __tablename__ = "memory_lifecycle"

    memory_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # active | superseded | merged | pattern | expired
    state: Mapped[str] = mapped_column(String(16), default="active")
    superseded_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    merged_into: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # dream | user | system
    actor: Mapped[str] = mapped_column(String(24), default="system")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MemoryAccess(Base):
    """How often a memory has actually been recalled.

    Decay (phase 08) ranks on this. Kept separate from MemoryLifecycle because
    it is written on every read while lifecycle is written rarely - one hot
    table and one cold one, rather than a single row rewritten constantly.
    """

    __tablename__ = "memory_access"

    memory_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last 20 access timestamps. Bounded so a hot memory's row cannot grow
    # without limit, but long enough to show a usage shape rather than a point.
    recent: Mapped[list | None] = mapped_column(JSON, nullable=True)


class MemoryFeedback(Base):
    """A person's verdict on whether a memory was any good.

    Append-only: someone changing their mind is a second row, not an edit. The
    history of what people thought is the signal Dream will read.
    """

    __tablename__ = "memory_feedback"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    memory_id: Mapped[str] = mapped_column(String(255), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[str] = mapped_column(String(8))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PatternSource(Base):
    """Which memories a Dream-synthesised pattern was drawn from.

    Populated in phase 07. Exists here because a pattern with no provenance is
    an assertion rather than a conclusion, and the table it points into is
    built now.
    """

    __tablename__ = "pattern_sources"
    __table_args__ = (
        UniqueConstraint("pattern_memory_id", "source_memory_id", name="uq_pattern_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    pattern_memory_id: Mapped[str] = mapped_column(String(255), index=True)
    source_memory_id: Mapped[str] = mapped_column(String(255), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GraphNode(Base):
    """A materialized graph node.

    This is a cache of what the entity store already implies, kept because
    re-deriving it per request was the slowest thing in the app. Treated as a
    cache throughout: a full rebuild is always available, and staleness is a
    performance problem rather than a correctness one.
    """

    __tablename__ = "graph_nodes"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    # "type:id" - already unique and already what the client uses, so a
    # surrogate key would add a lookup without adding information.
    entity_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    label: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(32))
    memory_count: Mapped[int] = mapped_column(Integer, default=0)
    # Denormalised so min_degree is a column predicate rather than a join and
    # a group-by on every request.
    degree: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class GraphEdge(Base):
    """A materialized co-occurrence edge, stored once, source-first."""

    __tablename__ = "graph_edges"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    source_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    target_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class DreamRun(Base):
    """One pass of background curation.

    Recorded whether or not it acted, including when it was skipped, because
    "Dream has not done anything" and "Dream has not run" are different
    problems with different fixes.
    """

    __tablename__ = "dream_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # supersede | merge | synthesis
    kind: Mapped[str] = mapped_column(String(16), index=True)
    # running | succeeded | failed | skipped
    status: Mapped[str] = mapped_column(String(16), default="running")
    scope: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    considered: Mapped[int] = mapped_column(Integer, default=0)
    acted: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)


class DreamAction(Base):
    """One thing Dream decided, and why.

    Reverting sets `reverted_at` rather than deleting: a reverted action is
    still something Dream did, and dropping the row would make the audit trail
    lie by omission.
    """

    __tablename__ = "dream_actions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dream_runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    subject_memory_id: Mapped[str] = mapped_column(String(255), index=True)
    object_memory_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DreamState(Base):
    """Cadence bookkeeping, one row per entity Dream has considered."""

    __tablename__ = "dream_state"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_type", "entity_id", name="uq_dream_state_entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[str] = mapped_column(String(255))
    last_synthesis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    memory_count_at_last_run: Mapped[int] = mapped_column(Integer, default=0)
    # Stamped when synthesis is switched on. Only memories created after it are
    # eligible, so enabling never triggers a bulk reprocess of history.
    enabled_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Hashes of source-id sets already synthesised, so a re-run cannot produce
    # a duplicate pattern.
    pattern_hashes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EntityAlias(Base):
    """One identifier that resolves to another.

    A person reaching the system from Telegram, the website and Discord is
    three identifiers and one person. An alias row says so, and reads expand
    through it so their memories stop fragmenting.

    The unique constraint is the whole design: an alias points at exactly one
    canonical, so resolution has one answer. Chains are collapsed on write -
    linking C to B when B already resolves to A stores C to A - which keeps
    resolution one hop and makes a cycle unrepresentable.
    """

    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_type", "alias_id", name="uq_entity_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(16))
    canonical_id: Mapped[str] = mapped_column(String(255))
    alias_id: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EntityProfile(Base):
    """Display metadata for an entity: a human name for an opaque id."""

    __tablename__ = "entity_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_type", "entity_id", name="uq_entity_profile"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    secret: Mapped[str] = mapped_column(Text)
    # How the payload is shaped on the wire: "generic" posts the raw signed
    # event, "discord" and "slack" post the message format those services
    # render. Defaults to generic so existing endpoints keep their contract.
    channel: Mapped[str] = mapped_column(String(32), default="generic")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class Backup(Base):
    """One snapshot attempt of the Postgres databases.

    A row is created when the run starts and updated in place as it progresses,
    so a crashed or killed run leaves a visible "running" record rather than
    disappearing. `verified_at` is set only after the dump has been read back
    and its structure checked - an unverified backup is not a backup.
    """

    __tablename__ = "backups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    # "manual" or "scheduled" - kept so retention can treat them differently.
    kind: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    # "local" or "s3://bucket/key" once uploaded.
    destination: Mapped[str] = mapped_column(String(512), default="local")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
