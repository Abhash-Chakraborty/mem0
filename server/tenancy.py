"""Organization and project scope resolution.

Every request that touches tenant data resolves its scope here, and every
visibility decision is made here. That is deliberate: project scoping is carried
in the memory *payload* rather than enforced by a foreign key, because memories
live in pgvector under the SDK's schema and we do not own that table. A payload
convention is only as strong as the discipline applying it, so there is exactly
one predicate - `visible_to` - and routes never decide scope by hand.

Reads filter in this layer rather than pushing project_id into the vector query.
The rule is "this project OR unstamped", the SDK's filter language is flat
equality with no OR, and an instance upgrading into tenancy has a whole store of
unstamped memories that must not vanish. Writes stamp via `scoped_metadata`, so
the unstamped set only ever shrinks.

Role ranks are compared numerically rather than by equality so a new role can be
inserted without revisiting every check.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import verify_auth
from db import get_db
from models import Membership, Organization, Project, ProjectMember, User

logger = logging.getLogger(__name__)

DEFAULT_ORG_SLUG = "default"
DEFAULT_PROJECT_SLUG = "default-project"

# The metadata key a memory is stamped with. Named once so a rename is a
# one-line change rather than a grep across every route.
PROJECT_KEY = "project_id"

# Higher rank means strictly more capability. Any check is "rank >= required".
ROLE_RANK: dict[str, int] = {
    "reader": 10,
    "member": 20,
    "admin": 30,
    "owner": 40,
}

# Header overrides, so a client can act on a project other than its default
# without a separate base URL per project.
ORG_HEADER = "X-Mem0-Org"
PROJECT_HEADER = "X-Mem0-Project"


@dataclass(frozen=True)
class Scope:
    """Resolved tenant context for one request."""

    org_id: uuid.UUID
    project_id: uuid.UUID
    role: str
    user_id: Optional[uuid.UUID] = None
    # True for the legacy ADMIN_API_KEY and AUTH_DISABLED paths, which have no
    # membership row but must not be locked out of their own instance.
    is_instance_admin: bool = False
    # The default project additionally owns every memory written before
    # migration 011, which carries no project stamp. See `visible_to`.
    is_default_project: bool = False

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)


def rank_of(role: str) -> int:
    return ROLE_RANK.get(role, 0)


def _default_org(db: Session) -> Optional[Organization]:
    return db.scalar(select(Organization).where(Organization.slug == DEFAULT_ORG_SLUG)) or db.scalar(
        select(Organization).order_by(Organization.created_at).limit(1)
    )


def _default_project(db: Session, org_id: uuid.UUID) -> Optional[Project]:
    return db.scalar(
        select(Project).where(Project.org_id == org_id, Project.slug == DEFAULT_PROJECT_SLUG)
    ) or db.scalar(select(Project).where(Project.org_id == org_id).order_by(Project.created_at).limit(1))


def _resolve_project(db: Session, org_id: uuid.UUID, requested: Optional[str]) -> tuple[Project, bool]:
    """Find a project by id or slug within an org, falling back to its default.

    Returns the project and whether it is the org's default, because the default
    additionally owns every unstamped memory and callers need to know which one
    they got without asking the database a second time.
    """
    default = _default_project(db, org_id)
    if default is None:
        raise HTTPException(
            status_code=500,
            detail="No project exists. Run migrations to create the default project.",
        )

    if not requested:
        return default, True

    project = None
    try:
        project = db.get(Project, uuid.UUID(requested))
    except (ValueError, AttributeError):
        project = db.scalar(select(Project).where(Project.org_id == org_id, Project.slug == requested))
    if project is None or project.org_id != org_id:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project, project.id == default.id


def _effective_role(db: Session, user_id: uuid.UUID, org_id: uuid.UUID, project_id: uuid.UUID) -> Optional[str]:
    """The role a user has on a project.

    The org membership grants the baseline. A project_members row can only
    narrow it - taking the lower of the two ranks - so adding a row can never
    accidentally hand out more access than the org role already allowed.
    """
    membership = db.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )
    if membership is None:
        return None

    override = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
    if override is None:
        return membership.role
    return membership.role if rank_of(membership.role) <= rank_of(override.role) else override.role


def _remember(request: Request, scope: Scope) -> Scope:
    """Stash the resolved project on the request for the logging middleware.

    The middleware runs outside the dependency graph, so it cannot ask for a
    Scope. Without this, every trace row would land with a null project and the
    Requests page would show one project another project's traffic.
    """
    request.state.scope_project_id = scope.project_id
    return scope


def require_scope(
    request: Request,
    user: Optional[User] = Depends(verify_auth),
    db: Session = Depends(get_db),
) -> Scope:
    """Resolve the org/project/role for this request.

    Three ways in, in priority order:

    1. An API key, which is bound to a project. The key wins over any header,
       so a leaked key cannot be pointed at a different project by adding one.
    2. A JWT, optionally narrowed by the org/project headers, checked against
       the caller's membership.
    3. The legacy admin key or AUTH_DISABLED, which get the default project at
       owner level so a fresh or bootstrap instance is usable.
    """
    auth_type = getattr(request.state, "auth_type", "none")

    if auth_type == "api_key":
        # Set by auth._resolve_user_from_api_key. A key minted before tenancy
        # existed has no project and falls through to the default below.
        key_project_id = getattr(request.state, "api_key_project_id", None)
        if key_project_id is not None:
            project = db.get(Project, key_project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="The project for this API key no longer exists.")
            role = "owner"
            if user is not None:
                role = _effective_role(db, user.id, project.org_id, project.id) or "member"
            default = _default_project(db, project.org_id)
            return _remember(request, Scope(
                org_id=project.org_id,
                project_id=project.id,
                role=role,
                user_id=getattr(user, "id", None),
                is_default_project=default is not None and default.id == project.id,
            ))

    org = _default_org(db)
    if org is None:
        raise HTTPException(
            status_code=500,
            detail="No organization exists. Run migrations to create the default organization.",
        )

    requested_org = request.headers.get(ORG_HEADER)
    if requested_org:
        found = None
        try:
            found = db.get(Organization, uuid.UUID(requested_org))
        except (ValueError, AttributeError):
            found = db.scalar(select(Organization).where(Organization.slug == requested_org))
        if found is None:
            raise HTTPException(status_code=404, detail="Organization not found.")
        org = found

    if auth_type in {"admin_api_key", "disabled"}:
        project, is_default = _resolve_project(db, org.id, request.headers.get(PROJECT_HEADER))
        return _remember(request, Scope(
            org_id=org.id,
            project_id=project.id,
            role="owner",
            user_id=getattr(user, "id", None),
            is_instance_admin=True,
            is_default_project=is_default,
        ))

    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Membership is checked before the project is resolved. The other order
    # leaks: an org the caller does not belong to would answer 500 "no project
    # exists" instead of 404, confirming the org is real.
    membership = db.scalar(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
    if membership is None:
        # 404 rather than 403 so the response does not confirm the org exists.
        raise HTTPException(status_code=404, detail="Organization not found.")

    project, is_default = _resolve_project(db, org.id, request.headers.get(PROJECT_HEADER))
    role = _effective_role(db, user.id, org.id, project.id) or membership.role

    return _remember(request, Scope(
        org_id=org.id,
        project_id=project.id,
        role=role,
        user_id=user.id,
        is_default_project=is_default,
    ))


def require_role(minimum: str):
    """Dependency factory enforcing a minimum role, e.g. Depends(require_role("admin"))."""

    required = rank_of(minimum)

    def _dependency(scope: Scope = Depends(require_scope)) -> Scope:
        if scope.rank < required:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires the {minimum} role or higher.",
            )
        return scope

    return _dependency


def scoped_metadata(scope: Scope, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Metadata to attach on write, stamping the memory with its project.

    PROJECT_KEY is forced last so a caller cannot smuggle a different project in
    through the metadata body.
    """
    metadata = dict(extra or {})
    metadata[PROJECT_KEY] = str(scope.project_id)
    return metadata


def entity_filters(extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Sanitise caller-supplied filters before they reach the SDK.

    Drops nulls and strips PROJECT_KEY: the project is never something a request
    gets to choose, and a filter that set it would read as scoping while
    actually bypassing `visible_to`.
    """
    return {k: v for k, v in (extra or {}).items() if v is not None and k != PROJECT_KEY}


def project_of(memory: Any) -> Optional[str]:
    """Read the project stamp off a memory, whichever shape it arrives in.

    The SDK hands back a raw pgvector payload in some paths and a serialized
    dict with a nested `metadata` in others, so both are checked rather than
    assuming one call site's shape holds everywhere.
    """
    if not isinstance(memory, dict):
        payload = getattr(memory, "payload", None)
        memory = payload if isinstance(payload, dict) else {}

    value = memory.get(PROJECT_KEY)
    if value is None:
        nested = memory.get("metadata")
        if isinstance(nested, dict):
            value = nested.get(PROJECT_KEY)
    return str(value) if value is not None else None


def visible_to(memory: Any, scope: Scope) -> bool:
    """Whether one memory is inside a scope. The single visibility rule.

    An unstamped memory belongs to the default project. That is what keeps an
    instance that upgraded into tenancy working: every memory written before
    migration 011 has no stamp, and hiding them all would look exactly like
    data loss to the person who upgraded.
    """
    owner = project_of(memory)
    if owner is None:
        return scope.is_default_project
    return owner == str(scope.project_id)


def filter_visible(memories: Any, scope: Scope) -> list[Any]:
    return [m for m in (memories or []) if visible_to(m, scope)]


def scope_results(response: Any, scope: Scope, top_k: Optional[int] = None) -> Any:
    """Apply `visible_to` to an SDK response, preserving its envelope.

    Filtering happens here rather than in the vector query because scoping needs
    "this project OR unstamped" and the SDK's filter language is flat equality
    with no OR. Trading a post-filter for a wrong answer is the right way round.
    """
    if isinstance(response, dict) and isinstance(response.get("results"), list):
        results = filter_visible(response["results"], scope)
        if top_k is not None:
            results = results[:top_k]
        return {**response, "results": results}
    if isinstance(response, list):
        results = filter_visible(response, scope)
        return results[:top_k] if top_k is not None else results
    return response


# Post-filtering can only shrink a result set, so a scoped read asks for more
# than it needs and trims after. Without this, `top_k=10` on an instance with a
# second project would quietly return fewer than ten rows that were available.
OVERFETCH_FACTOR = 3
OVERFETCH_CEILING = 1000
# With re-ranking on, a small top_k needs a wider candidate pool or the bias has
# nothing to reorder: asking for 3 and fetching 9 means decay can only shuffle
# nine rows. The floor gives it room without changing what the caller receives.
OVERFETCH_FLOOR_WHEN_RERANKING = 50


def overfetch(top_k: Optional[int], reranking: bool = False) -> Optional[int]:
    if top_k is None:
        return None
    widened = min(top_k * OVERFETCH_FACTOR, OVERFETCH_CEILING)
    if reranking:
        widened = min(max(widened, OVERFETCH_FLOOR_WHEN_RERANKING), OVERFETCH_CEILING)
    return widened
