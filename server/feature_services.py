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
from settings import (
    CATEGORY_CONFIDENCE_FLOOR,
    CATEGORY_MODEL,
    MAX_WEBHOOK_ATTEMPTS,
    WEBHOOK_TIMEOUT_SECONDS,
)

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


def apply_auto_add_categories(db: Session, memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach every active, auto-add category to a memory.

    Unlike the AI classifier this makes no judgment — flagged categories are
    always added. Uses on-conflict-do-nothing so an existing manual/AI
    assignment on the same (memory, category) is never downgraded to "auto".
    """
    memory_id = memory.get("id")
    if not memory_id:
        return []
    categories = db.scalars(
        select(Category).where(Category.is_active.is_(True), Category.auto_add.is_(True))
    ).all()
    if not categories:
        return []

    assignments = [
        {
            "memory_id": str(memory_id),
            "category_id": str(category.id),
            "confidence": None,
            "reason": "Auto-added (category rule)",
            "source": "auto",
        }
        for category in categories
    ]
    for assignment in assignments:
        stmt = insert(MemoryCategory).values(**assignment).on_conflict_do_nothing(constraint="uq_memory_category")
        db.execute(stmt)
    db.commit()
    return assignments


CATEGORY_PALETTE = [
    "#7c3aed", "#0ea5e9", "#f59e0b", "#10b981", "#ef4444",
    "#ec4899", "#8b5cf6", "#14b8a6", "#f97316", "#6366f1",
]


def _generate_categories_prompt(samples: list[str], existing: list[str], max_new: int) -> list[dict[str, str]]:
    existing_line = ", ".join(existing) if existing else "(none yet)"
    sample_block = "\n".join(f"- {text}" for text in samples)
    content = (
        f"You are organizing a personal memory store. Propose up to {max_new} broad, reusable "
        "categories that would neatly classify these memories. Prefer general buckets "
        "(e.g. Work, Health, Preferences, People, Travel, Finance) over narrow one-off labels. "
        f"Do NOT duplicate any of these existing categories: {existing_line}. "
        "Return strict JSON with key categories; each item has name (<=40 chars) and a short "
        "description (one sentence describing what belongs there).\n\n"
        f"Sample memories:\n{sample_block}"
    )
    return [
        {"role": "system", "content": "You design concise taxonomy categories. Return only JSON."},
        {"role": "user", "content": content},
    ]


def generate_categories(db: Session, max_new: int = 8, sample_size: int = 200) -> list[Category]:
    """Use the LLM to propose categories from existing memories, then create the new ones.

    Skips any proposed name that already exists (case-insensitive). Returns the
    Category rows that were created.
    """
    from server_state import get_memory_instance

    memories = list_memories(get_memory_instance(), limit=sample_size)
    samples = [str(memory.get("memory")) for memory in memories if memory.get("memory")][:sample_size]
    if not samples:
        return []

    existing = db.scalars(select(Category.name)).all()
    existing_lower = {name.lower() for name in existing}

    client_kwargs = {"api_key": os.environ.get("OPENAI_API_KEY")}
    if os.environ.get("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    client = OpenAI(**client_kwargs)
    response = client.chat.completions.create(
        model=CATEGORY_MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=_generate_categories_prompt(samples, list(existing), max_new),
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning("Category generator returned invalid JSON: %s", raw)
        return []

    created: list[Category] = []
    seen: set[str] = set(existing_lower)
    for index, item in enumerate(parsed.get("categories", [])):
        name = str(item.get("name") or "").strip()[:120]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        category = Category(
            name=name,
            description=str(item.get("description") or "").strip()[:1000],
            color=CATEGORY_PALETTE[index % len(CATEGORY_PALETTE)],
            auto_add=False,
        )
        db.add(category)
        created.append(category)
        if len(created) >= max_new:
            break

    if created:
        db.commit()
        for category in created:
            db.refresh(category)
    return created


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


def _is_add_event(log: RequestLog) -> bool:
    return log.method == "POST" and log.path == "/memories"


def _is_retrieval_event(log: RequestLog) -> bool:
    # Search is the primary retrieval path; GET /memories (list/get) also reads.
    return log.path == "/search" or (log.method == "GET" and log.path.startswith("/memories"))


def entity_counts(memories: list[dict[str, Any]]) -> dict[str, Any]:
    """Distinct entity ids per scope across the given memories."""
    buckets: dict[str, set[str]] = {"user": set(), "agent": set(), "run": set(), "app": set()}
    for memory in memories:
        for scope, field in (("user", "user_id"), ("agent", "agent_id"), ("run", "run_id")):
            value = memory.get(field)
            if value:
                buckets[scope].add(str(value))
        app_value = (memory.get("metadata") or {}).get("app_id")
        if app_value:
            buckets["app"].add(str(app_value))
    by_type = {scope: len(ids) for scope, ids in buckets.items()}
    return {"total": sum(by_type.values()), "by_type": by_type}


def dashboard_metrics(
    db: Session,
    memories: list[dict[str, Any]],
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Date-windowed request/event metrics plus current entity + memory snapshot.

    `memories` is the serialized memory list (passed in so callers can reuse it).
    `start`/`end` bound the request-log window; None means unbounded.
    """
    stmt = select(RequestLog)
    if start is not None:
        stmt = stmt.where(RequestLog.created_at >= start)
    if end is not None:
        stmt = stmt.where(RequestLog.created_at < end)
    logs = db.scalars(stmt.order_by(RequestLog.created_at)).all()

    total_requests = len(logs)
    successes = len([log for log in logs if log.status_code < 400])
    add_events = len([log for log in logs if _is_add_event(log)])
    retrieval_events = len([log for log in logs if _is_retrieval_event(log)])
    avg_latency = round(sum(log.latency_ms for log in logs) / total_requests, 2) if total_requests else 0

    series: dict[str, dict[str, Any]] = {}
    for log in logs:
        day = log.created_at.date().isoformat()
        bucket = series.setdefault(day, {"date": day, "requests": 0, "adds": 0, "retrievals": 0})
        bucket["requests"] += 1
        if _is_add_event(log):
            bucket["adds"] += 1
        if _is_retrieval_event(log):
            bucket["retrievals"] += 1

    # Memories added within the window (by payload created_at), for the in-range count.
    memories_in_range = 0
    for memory in memories:
        created = memory.get("created_at")
        parsed = None
        if created:
            try:
                parsed = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            except ValueError:
                parsed = None
        if parsed is None:
            continue
        if start is not None and parsed < start:
            continue
        if end is not None and parsed >= end:
            continue
        memories_in_range += 1

    entities = entity_counts(memories)
    entities_per_request = round(entities["total"] / total_requests, 2) if total_requests else 0

    return {
        "total_memories": len(memories),
        "memories_in_range": memories_in_range,
        "total_requests": total_requests,
        "add_events": add_events,
        "retrieval_events": retrieval_events,
        "success_rate": round(successes / total_requests * 100, 2) if total_requests else 0,
        "average_latency_ms": avg_latency,
        "entities_total": entities["total"],
        "entities_by_type": entities["by_type"],
        "entities_per_request": entities_per_request,
        "series": [series[day] for day in sorted(series)],
    }


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
