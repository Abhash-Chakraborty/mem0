import uuid
from typing import Any

from auth import require_admin
from db import get_db
from errors import upstream_error
from fastapi import APIRouter, Depends, HTTPException, Query
from feature_services import (
    apply_auto_add_categories,
    attach_categories,
    category_counts,
    classify_memory,
    get_memory,
    list_memories,
)
from models import Category, MemoryCategory
from pydantic import BaseModel, Field
from schemas import MessageResponse
from server_state import get_memory_instance
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

router = APIRouter(prefix="/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    color: str = "#7c3aed"
    auto_add: bool = False


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = None
    color: str | None = None
    is_active: bool | None = None
    auto_add: bool | None = None


class AssignCategoryRequest(BaseModel):
    category_id: str
    reason: str = "Manual assignment"


def _category_response(category: Category, count: int = 0) -> dict[str, Any]:
    return {
        "id": str(category.id),
        "name": category.name,
        "description": category.description,
        "color": category.color,
        "is_active": category.is_active,
        "auto_add": category.auto_add,
        "memory_count": count,
        "created_at": category.created_at.isoformat(),
        "updated_at": category.updated_at.isoformat(),
    }


@router.get("")
def list_categories(_auth=Depends(require_admin), db: Session = Depends(get_db)):
    counts = category_counts(db)
    categories = db.scalars(select(Category).order_by(Category.name)).all()
    return [_category_response(category, counts.get(str(category.id), 0)) for category in categories]


@router.post("")
def create_category(body: CategoryCreate, _auth=Depends(require_admin), db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required.")
    existing = db.scalar(select(Category).where(Category.name == name))
    if existing:
        raise HTTPException(status_code=409, detail="Category already exists.")
    category = Category(
        name=name,
        description=body.description.strip(),
        color=body.color.strip() or "#7c3aed",
        auto_add=body.auto_add,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return _category_response(category)


@router.patch("/{category_id}")
def update_category(
    category_id: str,
    body: CategoryUpdate,
    _auth=Depends(require_admin),
    db: Session = Depends(get_db),
):
    category = db.get(Category, uuid.UUID(category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found.")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Category name is required.")
        category.name = name
    if body.description is not None:
        category.description = body.description.strip()
    if body.color is not None:
        category.color = body.color.strip() or "#7c3aed"
    if body.is_active is not None:
        category.is_active = body.is_active
    if body.auto_add is not None:
        category.auto_add = body.auto_add
    db.commit()
    db.refresh(category)
    return _category_response(category, category_counts(db).get(str(category.id), 0))


@router.delete("/{category_id}", response_model=MessageResponse)
def delete_category(category_id: str, _auth=Depends(require_admin), db: Session = Depends(get_db)):
    category = db.get(Category, uuid.UUID(category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found.")
    db.delete(category)
    db.commit()
    return MessageResponse(message="Category deleted")


@router.get("/memories")
def list_category_memories(
    category_id: str | None = Query(default=None),
    _auth=Depends(require_admin),
    db: Session = Depends(get_db),
):
    memories = attach_categories(db, list_memories(get_memory_instance()))
    if category_id:
        memories = [
            memory
            for memory in memories
            if any(category["category_id"] == category_id for category in memory.get("categories", []))
        ]
    return {"results": memories}


@router.post("/memories/{memory_id}/classify")
def classify_memory_endpoint(memory_id: str, _auth=Depends(require_admin), db: Session = Depends(get_db)):
    memory = get_memory(get_memory_instance(), memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found.")
    try:
        classify_memory(db, memory)
    except Exception:
        raise upstream_error()
    return {"memory_id": memory_id, "assignments": attach_categories(db, [memory])[0]["categories"]}


@router.post("/memories/{memory_id}/assign")
def assign_category(
    memory_id: str,
    body: AssignCategoryRequest,
    _auth=Depends(require_admin),
    db: Session = Depends(get_db),
):
    category = db.get(Category, uuid.UUID(body.category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found.")
    stmt = (
        insert(MemoryCategory)
        .values(
            memory_id=memory_id,
            category_id=category.id,
            confidence=1,
            reason=body.reason,
            source="manual",
        )
        .on_conflict_do_update(
            constraint="uq_memory_category",
            set_={"confidence": 1, "reason": body.reason, "source": "manual"},
        )
    )
    db.execute(stmt)
    db.commit()
    return {"memory_id": memory_id, "categories": attach_categories(db, [{"id": memory_id}])[0]["categories"]}


@router.delete("/memories/{memory_id}/assign/{category_id}", response_model=MessageResponse)
def unassign_category(
    memory_id: str,
    category_id: str,
    _auth=Depends(require_admin),
    db: Session = Depends(get_db),
):
    db.execute(
        delete(MemoryCategory).where(
            MemoryCategory.memory_id == memory_id,
            MemoryCategory.category_id == uuid.UUID(category_id),
        )
    )
    db.commit()
    return MessageResponse(message="Category assignment removed")


@router.post("/reclassify")
def reclassify_all(_auth=Depends(require_admin), db: Session = Depends(get_db)):
    memories = list_memories(get_memory_instance())
    processed = 0
    for memory in memories:
        try:
            classify_memory(db, memory)
            apply_auto_add_categories(db, memory)
            processed += 1
        except Exception:
            continue
    return {"processed": processed, "total": len(memories)}
