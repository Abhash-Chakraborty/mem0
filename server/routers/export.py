import csv
import io
import json
from datetime import datetime
from datetime import timezone

from auth import require_admin
from db import get_db
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from feature_services import attach_categories, list_memories
from server_state import get_memory_instance
from sqlalchemy.orm import Session

router = APIRouter(prefix="/export", tags=["export"])


def _filter_memories(
    memories: list[dict],
    user_id: str | None,
    agent_id: str | None,
    run_id: str | None,
    category_id: str | None,
) -> list[dict]:
    filtered = memories
    if user_id:
        filtered = [memory for memory in filtered if memory.get("user_id") == user_id]
    if agent_id:
        filtered = [memory for memory in filtered if memory.get("agent_id") == agent_id]
    if run_id:
        filtered = [memory for memory in filtered if memory.get("run_id") == run_id]
    if category_id:
        filtered = [
            memory
            for memory in filtered
            if any(category["category_id"] == category_id for category in memory.get("categories", []))
        ]
    return filtered


@router.get("")
def export_memories(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    category_id: str | None = None,
    _auth=Depends(require_admin),
    db: Session = Depends(get_db),
):
    memories = attach_categories(db, list_memories(get_memory_instance()))
    memories = _filter_memories(memories, user_id, agent_id, run_id, category_id)
    exported_at = datetime.now(timezone.utc).isoformat()
    if format == "json":
        return JSONResponse({"exported_at": exported_at, "total": len(memories), "memories": memories})

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "memory", "user_id", "agent_id", "run_id", "created_at", "updated_at", "metadata", "categories"],
    )
    writer.writeheader()
    for memory in memories:
        writer.writerow(
            {
                "id": memory.get("id"),
                "memory": memory.get("memory"),
                "user_id": memory.get("user_id"),
                "agent_id": memory.get("agent_id"),
                "run_id": memory.get("run_id"),
                "created_at": memory.get("created_at"),
                "updated_at": memory.get("updated_at"),
                "metadata": json.dumps(memory.get("metadata") or {}, ensure_ascii=False),
                "categories": ", ".join(category["name"] for category in memory.get("categories", [])),
            }
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="abhash-memory-export.csv"'},
    )
