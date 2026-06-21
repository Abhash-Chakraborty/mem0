import hashlib
import hmac
import json
import logging
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from openai import OpenAI
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models import Category, MemoryCategory, RequestLog, WebhookDelivery, WebhookEndpoint

CATEGORY_MODEL = os.environ.get("MEM0_CATEGORY_LLM_MODEL") or os.environ.get("MEM0_DEFAULT_LLM_MODEL", "gpt-5.4-mini")
CATEGORY_CONFIDENCE_FLOOR = float(os.environ.get("MEM0_CATEGORY_CONFIDENCE_FLOOR", "0.45"))
MAX_WEBHOOK_ATTEMPTS = int(os.environ.get("MEM0_WEBHOOK_MAX_ATTEMPTS", "5"))
WEBHOOK_TIMEOUT_SECONDS = int(os.environ.get("MEM0_WEBHOOK_TIMEOUT_SECONDS", "8"))

RESERVED_PAYLOAD_KEYS = {"data", "user_id", "agent_id", "run_id", "hash", "created_at", "updated_at", "text_lemmatized"}
WEBHOOK_EVENTS = {"memory.created", "memory.updated", "memory.deleted", "search.performed", "webhook.test"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def serialize_memory_row(row: Any) -> dict[str, Any]:
    payload = getattr(row, "payload", None) or {}
    return {
        "id": getattr(row, "id", None),
        "memory": payload.get("data"),
        "user_id": payload.get("user_id"),
        "agent_id": payload.get("agent_id"),
        "run_id": payload.get("run_id"),
        "hash": payload.get("hash"),
        "metadata": {k: v for k, v in payload.items() if k not in RESERVED_PAYLOAD_KEYS},
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }


def list_memory_rows(memory_instance: Any, limit: int = 10_000) -> list[Any]:
    results = memory_instance.vector_store.list(top_k=limit)
    if results and isinstance(results, list) and isinstance(results[0], list):
        return results[0]
    return results or []


def list_memories(memory_instance: Any, limit: int = 10_000) -> list[dict[str, Any]]:
    return [serialize_memory_row(row) for row in list_memory_rows(memory_instance, limit)]


def get_memory(memory_instance: Any, memory_id: str) -> dict[str, Any] | None:
    row = memory_instance.vector_store.get(vector_id=memory_id)
    return serialize_memory_row(row) if row else None


def category_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(MemoryCategory.category_id, func.count(MemoryCategory.id)).group_by(MemoryCategory.category_id)
    ).all()
    return {str(category_id): count for category_id, count in rows}


def assignments_by_memory(db: Session, memory_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not memory_ids:
        return {}
    rows = (
        db.execute(
            select(MemoryCategory, Category)
            .join(Category, Category.id == MemoryCategory.category_id)
            .where(MemoryCategory.memory_id.in_(memory_ids))
            .order_by(Category.name)
        )
        .all()
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for assignment, category in rows:
        grouped.setdefault(assignment.memory_id, []).append(
            {
                "id": str(assignment.id),
                "category_id": str(category.id),
                "name": category.name,
                "color": category.color,
                "confidence": assignment.confidence,
                "reason": assignment.reason,
                "source": assignment.source,
                "created_at": assignment.created_at.isoformat(),
                "updated_at": assignment.updated_at.isoformat(),
            }
        )
    return grouped


def attach_categories(db: Session, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = assignments_by_memory(db, [str(memory.get("id")) for memory in memories if memory.get("id")])
    return [{**memory, "categories": grouped.get(str(memory.get("id")), [])} for memory in memories]


def _category_prompt(memory: dict[str, Any], categories: list[Category]) -> list[dict[str, str]]:
    category_lines = "\n".join(
        f"- id={category.id} name={category.name} description={category.description or '(no description)'}"
        for category in categories
    )
    content = (
        "Classify the memory into zero to three of the available categories. "
        "Only use category IDs from the list. Return strict JSON with key assignments. "
        "Each assignment must have category_id, confidence from 0 to 1, and reason. "
        "If no category fits, return {\"assignments\": []}.\n\n"
        f"Categories:\n{category_lines}\n\n"
        f"Memory:\n{json.dumps(memory, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": "You are a careful memory classification engine. Return only JSON."},
        {"role": "user", "content": content},
    ]


def classify_memory(db: Session, memory: dict[str, Any]) -> list[dict[str, Any]]:
    categories = db.scalars(select(Category).where(Category.is_active.is_(True)).order_by(Category.name)).all()
    if not categories or not memory.get("id") or not memory.get("memory"):
        return []

    client_kwargs = {"api_key": os.environ.get("OPENAI_API_KEY")}
    if os.environ.get("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    client = OpenAI(**client_kwargs)
    response = client.chat.completions.create(
        model=CATEGORY_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=_category_prompt(memory, list(categories)),
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning("Category classifier returned invalid JSON: %s", raw)
        return []

    valid_ids = {str(category.id) for category in categories}
    assignments = []
    for item in parsed.get("assignments", []):
        category_id = str(item.get("category_id", ""))
        confidence = float(item.get("confidence") or 0)
        if category_id not in valid_ids or confidence < CATEGORY_CONFIDENCE_FLOOR:
            continue
        assignments.append(
            {
                "memory_id": str(memory["id"]),
                "category_id": category_id,
                "confidence": min(max(confidence, 0), 1),
                "reason": str(item.get("reason") or "")[:1000],
                "source": "ai",
            }
        )

    db.execute(delete(MemoryCategory).where(MemoryCategory.memory_id == str(memory["id"]), MemoryCategory.source == "ai"))
    for assignment in assignments:
        stmt = (
            insert(MemoryCategory)
            .values(**assignment)
            .on_conflict_do_update(
                constraint="uq_memory_category",
                set_={
                    "confidence": assignment["confidence"],
                    "reason": assignment["reason"],
                    "source": assignment["source"],
                    "updated_at": utcnow(),
                },
            )
        )
        db.execute(stmt)
    db.commit()
    return assignments


def generate_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def webhook_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def enqueue_webhook_event(db: Session, event_type: str, payload: dict[str, Any]) -> int:
    if event_type not in WEBHOOK_EVENTS:
        return 0
    endpoints = db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.is_active.is_(True))).all()
    count = 0
    for endpoint in endpoints:
        if event_type not in (endpoint.events or []):
            continue
        db.add(
            WebhookDelivery(
                endpoint_id=endpoint.id,
                event_type=event_type,
                payload={"event": event_type, "created_at": utcnow().isoformat(), "data": payload},
                status="pending",
                next_attempt_at=utcnow(),
            )
        )
        count += 1
    if count:
        db.commit()
    return count


def _attempt_delivery(db: Session, delivery: WebhookDelivery, endpoint: WebhookEndpoint) -> None:
    body = json.dumps(delivery.payload, separators=(",", ":"), default=str).encode("utf-8")
    request = urllib.request.Request(
        endpoint.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Abhash-Memory-Webhooks/1.0",
            "X-Mem0-Event": delivery.event_type,
            "X-Mem0-Delivery": str(delivery.id),
            "X-Mem0-Signature-256": "sha256=" + webhook_signature(endpoint.secret, body),
        },
    )
    delivery.attempts += 1
    delivery.last_attempt_at = utcnow()
    try:
        with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:
            delivery.response_status = response.status
            delivery.response_body = response.read(2048).decode("utf-8", errors="replace")
            delivery.status = "delivered" if 200 <= response.status < 300 else "failed"
    except urllib.error.HTTPError as exc:
        delivery.response_status = exc.code
        delivery.response_body = exc.read(2048).decode("utf-8", errors="replace")
        delivery.status = "failed"
    except Exception as exc:
        delivery.response_status = None
        delivery.response_body = str(exc)[:2048]
        delivery.status = "failed"

    if delivery.status != "delivered" and delivery.attempts < MAX_WEBHOOK_ATTEMPTS:
        delay_seconds = min(300, 2 ** delivery.attempts * 15)
        delivery.status = "pending"
        delivery.next_attempt_at = utcnow() + timedelta(seconds=delay_seconds)
    else:
        delivery.next_attempt_at = None
    db.commit()


def process_due_webhooks(session_factory: Any, limit: int = 25) -> int:
    db = session_factory()
    processed = 0
    try:
        deliveries = (
            db.execute(
                select(WebhookDelivery, WebhookEndpoint)
                .join(WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.endpoint_id)
                .where(WebhookDelivery.status == "pending")
                .where(WebhookDelivery.next_attempt_at <= utcnow())
                .order_by(WebhookDelivery.created_at)
                .limit(limit)
            )
            .all()
        )
        for delivery, endpoint in deliveries:
            if not endpoint.is_active:
                delivery.status = "disabled"
                delivery.next_attempt_at = None
                db.commit()
                continue
            _attempt_delivery(db, delivery, endpoint)
            processed += 1
        return processed
    finally:
        db.close()


def request_analytics(db: Session, limit: int = 1000) -> dict[str, Any]:
    logs = db.scalars(select(RequestLog).order_by(RequestLog.created_at.desc()).limit(limit)).all()
    total = len(logs)
    successes = len([log for log in logs if log.status_code < 400])
    avg_latency = round(sum(log.latency_ms for log in logs) / total, 2) if total else 0
    by_path: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_day: dict[str, int] = {}
    for log in logs:
        by_path[log.path] = by_path.get(log.path, 0) + 1
        status_bucket = f"{log.status_code // 100}xx"
        by_status[status_bucket] = by_status.get(status_bucket, 0) + 1
        day = log.created_at.date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
    return {
        "total_requests": total,
        "success_rate": round(successes / total * 100, 2) if total else 0,
        "average_latency_ms": avg_latency,
        "by_path": sorted([{"path": path, "count": count} for path, count in by_path.items()], key=lambda x: -x["count"])[:10],
        "by_status": [{"status": status, "count": count} for status, count in sorted(by_status.items())],
        "by_day": [{"date": day, "count": count} for day, count in sorted(by_day.items())],
    }
