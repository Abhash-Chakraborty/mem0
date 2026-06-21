import uuid
from typing import Any

from auth import require_admin
from db import SessionLocal, get_db
from fastapi import APIRouter, Depends, HTTPException
from feature_services import WEBHOOK_EVENTS, generate_webhook_secret, process_due_webhooks, utcnow
from models import WebhookDelivery, WebhookEndpoint
from pydantic import BaseModel, Field, HttpUrl
from schemas import MessageResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    url: HttpUrl
    events: list[str]


class WebhookUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    url: HttpUrl | None = None
    events: list[str] | None = None
    is_active: bool | None = None


def _validate_events(events: list[str]) -> list[str]:
    if not events:
        raise HTTPException(status_code=400, detail="Select at least one webhook event.")
    invalid = sorted(set(events) - WEBHOOK_EVENTS)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unsupported events: {', '.join(invalid)}")
    return sorted(set(events))


def _endpoint_response(endpoint: WebhookEndpoint, include_secret: bool = False) -> dict[str, Any]:
    data = {
        "id": str(endpoint.id),
        "name": endpoint.name,
        "url": endpoint.url,
        "events": endpoint.events,
        "is_active": endpoint.is_active,
        "created_at": endpoint.created_at.isoformat(),
        "updated_at": endpoint.updated_at.isoformat(),
    }
    if include_secret:
        data["secret"] = endpoint.secret
    return data


def _delivery_response(delivery: WebhookDelivery) -> dict[str, Any]:
    return {
        "id": str(delivery.id),
        "endpoint_id": str(delivery.endpoint_id),
        "event_type": delivery.event_type,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "next_attempt_at": delivery.next_attempt_at.isoformat() if delivery.next_attempt_at else None,
        "last_attempt_at": delivery.last_attempt_at.isoformat() if delivery.last_attempt_at else None,
        "response_status": delivery.response_status,
        "response_body": delivery.response_body,
        "created_at": delivery.created_at.isoformat(),
    }


@router.get("")
def list_webhooks(_auth=Depends(require_admin), db: Session = Depends(get_db)):
    endpoints = db.scalars(select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc())).all()
    return [_endpoint_response(endpoint) for endpoint in endpoints]


@router.post("")
def create_webhook(body: WebhookCreate, _auth=Depends(require_admin), db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Webhook name is required.")
    endpoint = WebhookEndpoint(
        name=name,
        url=str(body.url),
        events=_validate_events(body.events),
        secret=generate_webhook_secret(),
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return _endpoint_response(endpoint, include_secret=True)


@router.get("/{endpoint_id}/deliveries")
def list_endpoint_deliveries(
    endpoint_id: str,
    _auth=Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.endpoint_id == uuid.UUID(endpoint_id))
        .order_by(WebhookDelivery.created_at.desc())
        .limit(200)
    )
    deliveries = db.scalars(stmt).all()
    return [_delivery_response(delivery) for delivery in deliveries]


@router.patch("/{endpoint_id}")
def update_webhook(endpoint_id: str, body: WebhookUpdate, _auth=Depends(require_admin), db: Session = Depends(get_db)):
    endpoint = db.get(WebhookEndpoint, uuid.UUID(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found.")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Webhook name is required.")
        endpoint.name = name
    if body.url is not None:
        endpoint.url = str(body.url)
    if body.events is not None:
        endpoint.events = _validate_events(body.events)
    if body.is_active is not None:
        endpoint.is_active = body.is_active
    db.commit()
    db.refresh(endpoint)
    return _endpoint_response(endpoint)


@router.delete("/{endpoint_id}", response_model=MessageResponse)
def delete_webhook(endpoint_id: str, _auth=Depends(require_admin), db: Session = Depends(get_db)):
    endpoint = db.get(WebhookEndpoint, uuid.UUID(endpoint_id))
    if endpoint:
        db.delete(endpoint)
        db.commit()
    return MessageResponse(message="Webhook endpoint deleted")


@router.post("/{endpoint_id}/regenerate-secret")
def regenerate_secret(endpoint_id: str, _auth=Depends(require_admin), db: Session = Depends(get_db)):
    endpoint = db.get(WebhookEndpoint, uuid.UUID(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found.")
    endpoint.secret = generate_webhook_secret()
    db.commit()
    db.refresh(endpoint)
    return _endpoint_response(endpoint, include_secret=True)


@router.post("/{endpoint_id}/test")
def test_webhook(endpoint_id: str, _auth=Depends(require_admin), db: Session = Depends(get_db)):
    endpoint = db.get(WebhookEndpoint, uuid.UUID(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found.")
    db.add(
        WebhookDelivery(
            endpoint_id=endpoint.id,
            event_type="webhook.test",
            payload={
                "event": "webhook.test",
                "created_at": utcnow().isoformat(),
                "data": {"message": "Test delivery from Abhash Memory"},
            },
            status="pending",
            next_attempt_at=utcnow(),
        )
    )
    db.commit()
    process_due_webhooks(SessionLocal)
    return {"queued": 1}


@router.get("/deliveries")
def list_deliveries(
    endpoint_id: str | None = None,
    _auth=Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(200)
    if endpoint_id:
        stmt = stmt.where(WebhookDelivery.endpoint_id == uuid.UUID(endpoint_id))
    deliveries = db.scalars(stmt).all()
    return [_delivery_response(delivery) for delivery in deliveries]
