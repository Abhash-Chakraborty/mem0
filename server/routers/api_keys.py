import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import generate_api_key, require_auth
from db import get_db
from models import APIKey, Project, User
from schemas import MessageResponse
from tenancy import Scope, require_scope

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateKeyRequest(BaseModel):
    label: str


class CreateKeyResponse(BaseModel):
    id: str
    key: str
    label: str
    key_prefix: str
    project_id: str
    project_name: str
    created_at: datetime


class KeyListItem(BaseModel):
    id: str
    label: str
    key_prefix: str
    project_id: str | None
    project_name: str | None
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[KeyListItem])
def list_keys(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    keys = (
        db.execute(
            select(APIKey)
            .where(APIKey.created_by == user.id, APIKey.revoked_at.is_(None))
            .order_by(APIKey.created_at.desc())
        )
        .scalars()
        .all()
    )
    # Every key across every project the caller owns is listed, deliberately:
    # this page answers "what can reach my data", and hiding out-of-scope keys
    # behind the current project switch would hide exactly what needs revoking.
    names = {
        p.id: p.name
        for p in db.execute(select(Project).where(Project.id.in_([k.project_id for k in keys if k.project_id])))
        .scalars()
        .all()
    } if keys else {}

    return [
        KeyListItem(
            id=str(k.id),
            label=k.label,
            key_prefix=k.key_prefix,
            project_id=str(k.project_id) if k.project_id else None,
            project_name=names.get(k.project_id),
            created_at=k.created_at,
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.post("", response_model=CreateKeyResponse, status_code=201)
def create_key(
    body: CreateKeyRequest,
    user: User = Depends(require_auth),
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """Mint a key bound to the project the request was scoped to.

    The binding is on the key itself rather than on the caller's headers,
    because a key outlives the session that created it and must not widen its
    reach when the creator later switches project.
    """
    full_key, prefix, key_hash = generate_api_key()
    api_key = APIKey(
        key_prefix=prefix,
        key_hash=key_hash,
        label=body.label,
        created_by=user.id,
        project_id=scope.project_id,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    project = db.get(Project, scope.project_id)
    return CreateKeyResponse(
        id=str(api_key.id),
        key=full_key,
        label=api_key.label,
        key_prefix=prefix,
        project_id=str(scope.project_id),
        project_name=project.name if project else "",
        created_at=api_key.created_at,
    )


@router.delete("/{key_id}", response_model=MessageResponse)
def revoke_key(key_id: str, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        key_uuid = uuid.UUID(key_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="API key not found.")
    api_key = db.get(APIKey, key_uuid)
    if api_key is None or api_key.created_by != user.id:
        raise HTTPException(status_code=404, detail="API key not found.")
    if api_key.revoked_at is not None:
        raise HTTPException(status_code=400, detail="API key is already revoked.")

    api_key.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return MessageResponse(message="API key revoked.")
