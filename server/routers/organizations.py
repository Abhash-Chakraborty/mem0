"""Organization, project, member and invite management.

Two rules run through every handler here and are worth stating once:

1. The org in the path is always checked against the caller's membership, never
   against the request scope alone. The scope headers say which org the caller
   *wants*; membership says which they may have.
2. An organization can never be left without an owner. Every path that could
   remove one - role change, member removal, self-departure - counts the
   remaining owners first. Locking the last owner out of a self-hosted instance
   has no support desk to undo it.
"""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import project_settings
from auth import require_auth
from db import get_db
from models import APIKey, Invite, Membership, Organization, Project, ProjectMember, User
from schemas import MessageResponse
from tenancy import (
    DEFAULT_PROJECT_SLUG,
    ROLE_RANK,
    Scope,
    rank_of,
    require_role,
    require_scope,
)

router = APIRouter(tags=["tenancy"])

INVITE_TTL_DAYS = 14
ASSIGNABLE_ROLES = tuple(ROLE_RANK)


# ---------------------------------------------------------------- helpers


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def _unique_slug(db: Session, base: str, org_id: Optional[uuid.UUID]) -> str:
    """A slug that does not collide, disambiguated with a numeric suffix.

    Racing writers can still collide; the unique constraint catches that and the
    caller sees a 409 rather than two projects sharing a slug.
    """
    slug = _slugify(base)
    candidate = slug
    n = 2
    while True:
        if org_id is None:
            taken = db.scalar(select(Organization.id).where(Organization.slug == candidate))
        else:
            taken = db.scalar(
                select(Project.id).where(Project.org_id == org_id, Project.slug == candidate)
            )
        if taken is None:
            return candidate
        candidate = f"{slug}-{n}"
        n += 1


def _hash_invite_token(token: str) -> str:
    """SHA-256, not bcrypt.

    An invite token is 32 bytes of CSPRNG output, so it needs no work factor to
    resist guessing - and a deterministic digest is what makes redeeming an
    invite a single indexed lookup instead of a bcrypt verify against every
    outstanding row.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def _membership(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Membership]:
    return db.scalar(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id))


def _require_org_access(db: Session, org_id_raw: str, user: User, minimum: str = "reader") -> tuple[Organization, Membership]:
    """Resolve an org from the path and confirm the caller may act on it.

    404 rather than 403 for a non-member, so the response does not confirm that
    an org with that id exists.
    """
    try:
        org_id = uuid.UUID(org_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Organization not found.")

    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found.")

    membership = _membership(db, org.id, user.id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if rank_of(membership.role) < rank_of(minimum):
        raise HTTPException(status_code=403, detail=f"This action requires the {minimum} role or higher.")
    return org, membership


def _owner_count(db: Session, org_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count(Membership.id)).where(Membership.org_id == org_id, Membership.role == "owner")
    ) or 0


def _guard_last_owner(db: Session, membership: Membership, action: str) -> None:
    if membership.role == "owner" and _owner_count(db, membership.org_id) <= 1:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot {action}: an organization must always have at least one owner.",
        )


def _project_or_404(db: Session, project_id_raw: str, org_id: uuid.UUID) -> Project:
    try:
        project_id = uuid.UUID(project_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Project not found.")
    project = db.get(Project, project_id)
    if project is None or project.org_id != org_id:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _validate_role(role: str) -> str:
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role '{role}'. Expected one of: {', '.join(ASSIGNABLE_ROLES)}.",
        )
    return role


# ---------------------------------------------------------------- schemas


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    role: str
    project_count: int
    member_count: int
    created_at: datetime


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrgUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectOut(BaseModel):
    id: str
    org_id: str
    name: str
    slug: str
    description: str
    settings: dict[str, Any]
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class MemberOut(BaseModel):
    user_id: str
    name: str
    email: str
    # `role` is always the organization role, on every endpoint that returns
    # this model. The project view adds the narrowing and the result of
    # applying it as separate fields rather than overwriting `role`, so the
    # same field never means two things depending on which route answered.
    role: str
    project_role: Optional[str] = None
    effective_role: Optional[str] = None
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    role: str


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "member"


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    expires_at: datetime
    created_at: datetime
    accepted_at: Optional[datetime] = None


class InviteCreated(InviteOut):
    # Returned exactly once, at creation. Only the hash is stored.
    token: str


class InviteAccept(BaseModel):
    token: str


class ScopeOut(BaseModel):
    org_id: str
    org_name: str
    org_slug: str
    project_id: str
    project_name: str
    project_slug: str
    role: str
    is_default_project: bool


# ---------------------------------------------------------------- scope


@router.get("/scope", response_model=ScopeOut, summary="Resolve the caller's current scope")
def current_scope(scope: Scope = Depends(require_scope), db: Session = Depends(get_db)):
    """What org and project this request would act on, and at what role.

    The dashboard calls this to render its switchers, so it reflects the same
    header resolution every other route goes through rather than a second
    implementation of the same rules.
    """
    org = db.get(Organization, scope.org_id)
    project = db.get(Project, scope.project_id)
    if org is None or project is None:
        raise HTTPException(status_code=500, detail="Scope references a missing organization or project.")
    return ScopeOut(
        org_id=str(org.id),
        org_name=org.name,
        org_slug=org.slug,
        project_id=str(project.id),
        project_name=project.name,
        project_slug=project.slug,
        role=scope.role,
        is_default_project=scope.is_default_project,
    )


# ---------------------------------------------------------------- orgs


@router.get("/orgs", response_model=list[OrgOut], summary="List organizations the caller belongs to")
def list_orgs(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.created_at)
    ).all()

    return [
        OrgOut(
            id=str(org.id),
            name=org.name,
            slug=org.slug,
            role=role,
            project_count=db.scalar(select(func.count(Project.id)).where(Project.org_id == org.id)) or 0,
            member_count=db.scalar(select(func.count(Membership.id)).where(Membership.org_id == org.id)) or 0,
            created_at=org.created_at,
        )
        for org, role in rows
    ]


@router.post("/orgs", response_model=OrgOut, status_code=201, summary="Create an organization")
def create_org(body: OrgCreate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    """Create an org, its default project, and the caller's owner membership.

    All three in one transaction: an org with no owner is unusable and an org
    with no project fails scope resolution on the next request.
    """
    org = Organization(name=body.name.strip(), slug=_unique_slug(db, body.name, None))
    db.add(org)
    db.flush()

    db.add(Project(org_id=org.id, name="default-project", slug=DEFAULT_PROJECT_SLUG, description=""))
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(org)

    return OrgOut(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        role="owner",
        project_count=1,
        member_count=1,
        created_at=org.created_at,
    )


@router.patch("/orgs/{org_id}", response_model=OrgOut, summary="Rename an organization")
def update_org(org_id: str, body: OrgUpdate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    org, membership = _require_org_access(db, org_id, user, minimum="admin")
    org.name = body.name.strip()
    db.commit()
    db.refresh(org)
    return OrgOut(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        role=membership.role,
        project_count=db.scalar(select(func.count(Project.id)).where(Project.org_id == org.id)) or 0,
        member_count=db.scalar(select(func.count(Membership.id)).where(Membership.org_id == org.id)) or 0,
        created_at=org.created_at,
    )


@router.delete("/orgs/{org_id}", response_model=MessageResponse, summary="Delete an organization")
def delete_org(org_id: str, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    """Delete an org and everything under it. Refuses to delete the last one.

    Deleting the only org would leave the instance with no tenant to resolve a
    scope against, which reads to the operator as a total outage.
    """
    org, _ = _require_org_access(db, org_id, user, minimum="owner")
    if (db.scalar(select(func.count(Organization.id))) or 0) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only organization on this instance.")
    db.delete(org)
    db.commit()
    return MessageResponse(message="Organization deleted.")


# ---------------------------------------------------------------- members


@router.get("/orgs/{org_id}/members", response_model=list[MemberOut], summary="List organization members")
def list_members(org_id: str, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    org, _ = _require_org_access(db, org_id, user)
    rows = db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org.id)
        .order_by(Membership.created_at)
    ).all()
    return [
        MemberOut(
            user_id=str(member.id),
            name=member.name,
            email=member.email,
            role=membership.role,
            joined_at=membership.created_at,
        )
        for member, membership in rows
    ]


@router.patch(
    "/orgs/{org_id}/members/{member_id}",
    response_model=MemberOut,
    summary="Change a member's role",
)
def update_member_role(
    org_id: str,
    member_id: str,
    body: MemberRoleUpdate,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    org, actor = _require_org_access(db, org_id, user, minimum="admin")
    role = _validate_role(body.role)

    # An admin cannot mint an owner: granting a rank you do not hold is how a
    # compromised admin account becomes a compromised instance.
    if rank_of(role) > rank_of(actor.role):
        raise HTTPException(status_code=403, detail="You cannot grant a role higher than your own.")

    try:
        target_id = uuid.UUID(member_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Member not found.")

    membership = _membership(db, org.id, target_id)
    target = db.get(User, target_id)
    if membership is None or target is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if rank_of(membership.role) > rank_of(actor.role):
        raise HTTPException(status_code=403, detail="You cannot change the role of a higher-ranked member.")
    if rank_of(role) < rank_of(membership.role):
        _guard_last_owner(db, membership, "demote this member")

    membership.role = role
    db.commit()
    db.refresh(membership)
    return MemberOut(
        user_id=str(target.id),
        name=target.name,
        email=target.email,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.delete(
    "/orgs/{org_id}/members/{member_id}",
    response_model=MessageResponse,
    summary="Remove a member from an organization",
)
def remove_member(
    org_id: str,
    member_id: str,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    try:
        target_id = uuid.UUID(member_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Member not found.")

    # Leaving is always allowed; removing someone else needs admin.
    minimum = "reader" if target_id == user.id else "admin"
    org, actor = _require_org_access(db, org_id, user, minimum=minimum)

    membership = _membership(db, org.id, target_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if target_id != user.id and rank_of(membership.role) > rank_of(actor.role):
        raise HTTPException(status_code=403, detail="You cannot remove a higher-ranked member.")
    _guard_last_owner(db, membership, "remove this member")

    db.execute(
        ProjectMember.__table__.delete().where(
            ProjectMember.user_id == target_id,
            ProjectMember.project_id.in_(select(Project.id).where(Project.org_id == org.id)),
        )
    )
    db.delete(membership)
    db.commit()
    return MessageResponse(message="Member removed.")


# ---------------------------------------------------------------- invites


@router.get("/orgs/{org_id}/invites", response_model=list[InviteOut], summary="List pending invites")
def list_invites(org_id: str, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    org, _ = _require_org_access(db, org_id, user, minimum="admin")
    invites = (
        db.execute(
            select(Invite)
            .where(Invite.org_id == org.id, Invite.accepted_at.is_(None))
            .order_by(Invite.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        InviteOut(
            id=str(i.id),
            email=i.email,
            role=i.role,
            expires_at=i.expires_at,
            created_at=i.created_at,
            accepted_at=i.accepted_at,
        )
        for i in invites
    ]


@router.post(
    "/orgs/{org_id}/invites",
    response_model=InviteCreated,
    status_code=201,
    summary="Invite someone to an organization",
)
def create_invite(
    org_id: str,
    body: InviteCreate,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Mint an invite token.

    This instance has no mail transport, so the token comes back in the response
    for the admin to hand over out of band. That is the honest behaviour: a
    silent "invite sent" for mail that never leaves would be worse.
    """
    org, actor = _require_org_access(db, org_id, user, minimum="admin")
    role = _validate_role(body.role)
    if rank_of(role) > rank_of(actor.role):
        raise HTTPException(status_code=403, detail="You cannot invite someone at a role higher than your own.")

    email = body.email.lower()
    existing_user = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing_user is not None and _membership(db, org.id, existing_user.id) is not None:
        raise HTTPException(status_code=409, detail="That person is already a member of this organization.")

    token = f"m0inv_{secrets.token_urlsafe(32)}"
    invite = Invite(
        org_id=org.id,
        email=email,
        role=role,
        token_hash=_hash_invite_token(token),
        invited_by=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    return InviteCreated(
        id=str(invite.id),
        email=invite.email,
        role=invite.role,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        accepted_at=None,
        token=token,
    )


@router.delete(
    "/orgs/{org_id}/invites/{invite_id}",
    response_model=MessageResponse,
    summary="Revoke a pending invite",
)
def revoke_invite(
    org_id: str,
    invite_id: str,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    org, _ = _require_org_access(db, org_id, user, minimum="admin")
    try:
        invite = db.get(Invite, uuid.UUID(invite_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite is None or invite.org_id != org.id:
        raise HTTPException(status_code=404, detail="Invite not found.")
    db.delete(invite)
    db.commit()
    return MessageResponse(message="Invite revoked.")


@router.post("/invites/accept", response_model=OrgOut, summary="Accept an invitation")
def accept_invite(body: InviteAccept, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    """Redeem an invite for the signed-in account.

    The invite's email must match the account redeeming it, so a leaked token
    cannot be used by whoever happens to find it.
    """
    invite = db.scalar(select(Invite).where(Invite.token_hash == _hash_invite_token(body.token)))
    if invite is None or invite.accepted_at is not None:
        raise HTTPException(status_code=404, detail="Invitation not found or already used.")

    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This invitation has expired.")
    if invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="This invitation was issued to a different email address.")

    org = db.get(Organization, invite.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="The organization for this invitation no longer exists.")

    if _membership(db, org.id, user.id) is None:
        db.add(Membership(org_id=org.id, user_id=user.id, role=invite.role))
    invite.accepted_at = datetime.now(timezone.utc)
    db.commit()

    return OrgOut(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        role=invite.role,
        project_count=db.scalar(select(func.count(Project.id)).where(Project.org_id == org.id)) or 0,
        member_count=db.scalar(select(func.count(Membership.id)).where(Membership.org_id == org.id)) or 0,
        created_at=org.created_at,
    )


# ---------------------------------------------------------------- projects


def _project_out(project: Project, is_default: bool) -> ProjectOut:
    return ProjectOut(
        id=str(project.id),
        org_id=str(project.org_id),
        name=project.name,
        slug=project.slug,
        description=project.description or "",
        # Resolved, not raw: a project created before a setting existed has no
        # key for it, and every client would otherwise need its own copy of the
        # defaults to render a form.
        settings=project_settings.resolve(project.settings),
        is_default=is_default,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _default_project_id(db: Session, org_id: uuid.UUID) -> Optional[uuid.UUID]:
    project = db.scalar(
        select(Project).where(Project.org_id == org_id, Project.slug == DEFAULT_PROJECT_SLUG)
    ) or db.scalar(select(Project).where(Project.org_id == org_id).order_by(Project.created_at).limit(1))
    return project.id if project else None


@router.get("/projects", response_model=list[ProjectOut], summary="List projects in the current organization")
def list_projects(scope: Scope = Depends(require_scope), db: Session = Depends(get_db)):
    """Projects in the scoped org, minus any the caller has been narrowed out of.

    A `project_members` row exists only to restrict, so a row at rank zero is
    how a member is kept out of a project entirely.
    """
    projects = (
        db.execute(select(Project).where(Project.org_id == scope.org_id).order_by(Project.created_at))
        .scalars()
        .all()
    )
    default_id = _default_project_id(db, scope.org_id)

    if scope.user_id is not None and projects:
        narrowed = {
            row.project_id: row.role
            for row in db.execute(
                select(ProjectMember).where(
                    ProjectMember.user_id == scope.user_id,
                    ProjectMember.project_id.in_([p.id for p in projects]),
                )
            ).scalars()
        }
        # Absent row means "org role applies", which is why the default here is
        # a rank that always passes rather than a lookup of the org role.
        projects = [p for p in projects if rank_of(narrowed.get(p.id, "owner")) > 0]

    return [_project_out(p, p.id == default_id) for p in projects]


@router.post("/projects", response_model=ProjectOut, status_code=201, summary="Create a project")
def create_project(
    body: ProjectCreate,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    project = Project(
        org_id=scope.org_id,
        name=body.name.strip(),
        slug=_unique_slug(db, body.name, scope.org_id),
        description=body.description or "",
        settings={},
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_out(project, is_default=False)


@router.get("/projects/{project_id}", response_model=ProjectOut, summary="Get a project")
def get_project(project_id: str, scope: Scope = Depends(require_scope), db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id, scope.org_id)
    return _project_out(project, project.id == _default_project_id(db, scope.org_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut, summary="Update a project")
def update_project(
    project_id: str,
    body: ProjectUpdate,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Rename a project or edit its settings.

    `settings` merges section by section through project_settings.merge, not as
    a shallow dict update. Four separate settings pages each own one section,
    and a shallow merge would let whichever saved last replace a section it
    never displayed.
    """
    project = _project_or_404(db, project_id, scope.org_id)
    if body.name is not None:
        project.name = body.name.strip()
    if body.description is not None:
        project.description = body.description
    if body.settings is not None:
        project.settings = project_settings.merge(project.settings, body.settings)
    db.commit()
    db.refresh(project)
    return _project_out(project, project.id == _default_project_id(db, scope.org_id))


@router.delete("/projects/{project_id}", response_model=MessageResponse, summary="Delete a project")
def delete_project(
    project_id: str,
    scope: Scope = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    """Delete a project. The org's default project cannot be deleted.

    The default project owns every memory written before tenancy existed, so
    deleting it would orphan them with no route left that can see them.
    """
    project = _project_or_404(db, project_id, scope.org_id)
    if project.id == _default_project_id(db, scope.org_id):
        raise HTTPException(status_code=400, detail="The default project cannot be deleted.")

    # API keys cascade with the project, so a key bound to it stops working
    # rather than silently falling back to another project's memories.
    db.execute(APIKey.__table__.delete().where(APIKey.project_id == project.id))
    db.delete(project)
    db.commit()
    return MessageResponse(message="Project deleted.")


@router.get(
    "/projects/{project_id}/members",
    response_model=list[MemberOut],
    summary="List effective access to a project",
)
def list_project_members(
    project_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """Everyone in the org, with their effective role on this project.

    Org members appear whether or not they have a narrowing row, because "who
    can reach this project" is the question being asked - not "who has an
    override".
    """
    project = _project_or_404(db, project_id, scope.org_id)
    rows = db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == scope.org_id)
        .order_by(Membership.created_at)
    ).all()
    overrides = {
        row.user_id: row.role
        for row in db.execute(select(ProjectMember).where(ProjectMember.project_id == project.id)).scalars()
    }

    out = []
    for member, membership in rows:
        override = overrides.get(member.id)
        effective = membership.role
        if override is not None and rank_of(override) < rank_of(membership.role):
            effective = override
        out.append(
            MemberOut(
                user_id=str(member.id),
                name=member.name,
                email=member.email,
                role=membership.role,
                project_role=override,
                effective_role=effective,
                joined_at=membership.created_at,
            )
        )
    return out


@router.put(
    "/projects/{project_id}/members/{member_id}",
    response_model=MemberOut,
    summary="Narrow a member's role on a project",
)
def set_project_role(
    project_id: str,
    member_id: str,
    body: MemberRoleUpdate,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Restrict one member's access to one project.

    A narrowing row can only lower a role. Asking for a higher one is rejected
    outright rather than silently clamped, so the caller learns the rule instead
    of wondering why their write did nothing.
    """
    project = _project_or_404(db, project_id, scope.org_id)
    role = _validate_role(body.role)

    try:
        target_id = uuid.UUID(member_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Member not found.")

    membership = _membership(db, scope.org_id, target_id)
    target = db.get(User, target_id)
    if membership is None or target is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if rank_of(role) > rank_of(membership.role):
        raise HTTPException(
            status_code=400,
            detail=(
                f"A project role can only narrow the organization role. "
                f"This member is '{membership.role}' in the organization."
            ),
        )

    existing = db.scalar(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == target_id)
    )
    if existing is None:
        existing = ProjectMember(project_id=project.id, user_id=target_id, role=role)
        db.add(existing)
    else:
        existing.role = role
    db.commit()
    db.refresh(existing)

    return MemberOut(
        user_id=str(target.id),
        name=target.name,
        email=target.email,
        role=membership.role,
        project_role=existing.role,
        effective_role=existing.role,
        joined_at=membership.created_at,
    )


@router.delete(
    "/projects/{project_id}/members/{member_id}",
    response_model=MessageResponse,
    summary="Remove a project-level narrowing",
)
def clear_project_role(
    project_id: str,
    member_id: str,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Drop the narrowing row, restoring the member's full org role here."""
    project = _project_or_404(db, project_id, scope.org_id)
    try:
        target_id = uuid.UUID(member_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Member not found.")

    existing = db.scalar(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == target_id)
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="This member has no project-level role to remove.")
    db.delete(existing)
    db.commit()
    return MessageResponse(message="Project role removed; the organization role now applies.")
