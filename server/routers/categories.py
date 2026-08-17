import uuid
from typing import Any

from db import get_db
from errors import upstream_error
from fastapi import APIRouter, Depends, HTTPException, Query
from feature_services import (
    apply_auto_add_categories,
    attach_categories,
    category_counts,
    classify_memory,
    generate_categories,
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
from tenancy import Scope, require_role, require_scope, scope_results, visible_to

router = APIRouter(prefix="/categories", tags=["categories"])


def _scoped(db: Session, category_id: str, scope: Scope) -> Category:
    """Fetch a category and confirm it belongs to the caller's project.

    404 on a category from another project, not 403: the id should not be
    usable to discover what other projects have named things.
    """
    try:
        category = db.get(Category, uuid.UUID(category_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Category not found.")
    if category is None or category.project_id != scope.project_id:
        raise HTTPException(status_code=404, detail="Category not found.")
    return category


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
def list_categories(scope: Scope = Depends(require_scope), db: Session = Depends(get_db)):
    counts = category_counts(db, scope.project_id)
    categories = db.scalars(
        select(Category).where(Category.project_id == scope.project_id).order_by(Category.name)
    ).all()
    return [_category_response(category, counts.get(str(category.id), 0)) for category in categories]


@router.post("")
def create_category(
    body: CategoryCreate,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required.")
    existing = db.scalar(
        select(Category).where(Category.project_id == scope.project_id, Category.name == name)
    )
    if existing:
        raise HTTPException(status_code=409, detail="Category already exists in this project.")
    category = Category(
        project_id=scope.project_id,
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
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    category = _scoped(db, category_id, scope)
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
    return _category_response(category, category_counts(db, scope.project_id).get(str(category.id), 0))


@router.delete("/{category_id}", response_model=MessageResponse)
def delete_category(
    category_id: str,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    category = _scoped(db, category_id, scope)
    db.delete(category)
    db.commit()
    return MessageResponse(message="Category deleted")


@router.get("/memories")
def list_category_memories(
    category_id: str | None = Query(default=None),
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    visible = scope_results(list_memories(get_memory_instance()), scope)
    memories = attach_categories(db, visible)
    if category_id:
        memories = [
            memory
            for memory in memories
            if any(category["category_id"] == category_id for category in memory.get("categories", []))
        ]
    return {"results": memories}


@router.post("/memories/{memory_id}/classify")
def classify_memory_endpoint(
    memory_id: str,
    scope: Scope = Depends(require_role("member")),
    db: Session = Depends(get_db),
):
    memory = get_memory(get_memory_instance(), memory_id)
    if not memory or not visible_to(memory, scope):
        raise HTTPException(status_code=404, detail="Memory not found.")
    try:
        classify_memory(db, memory, scope.project_id)
    except Exception:
        raise upstream_error()
    return {"memory_id": memory_id, "assignments": attach_categories(db, [memory])[0]["categories"]}


@router.post("/memories/{memory_id}/assign")
def assign_category(
    memory_id: str,
    body: AssignCategoryRequest,
    scope: Scope = Depends(require_role("member")),
    db: Session = Depends(get_db),
):
    category = _scoped(db, body.category_id, scope)
    memory = get_memory(get_memory_instance(), memory_id)
    if not memory or not visible_to(memory, scope):
        raise HTTPException(status_code=404, detail="Memory not found.")
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
    scope: Scope = Depends(require_role("member")),
    db: Session = Depends(get_db),
):
    _scoped(db, category_id, scope)
    db.execute(
        delete(MemoryCategory).where(
            MemoryCategory.memory_id == memory_id,
            MemoryCategory.category_id == uuid.UUID(category_id),
        )
    )
    db.commit()
    return MessageResponse(message="Category assignment removed")


@router.post("/auto-generate")
def auto_generate_categories(
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Have the LLM propose categories from this project's memories and create the new ones."""
    try:
        created = generate_categories(db, project_id=scope.project_id)
    except Exception:
        raise upstream_error()
    return {
        "created": [_category_response(category) for category in created],
        "count": len(created),
    }


@router.post("/reclassify")
def reclassify_all(
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    memories = scope_results(list_memories(get_memory_instance()), scope)
    processed = 0
    for memory in memories:
        try:
            classify_memory(db, memory, scope.project_id)
            apply_auto_add_categories(db, memory, scope.project_id)
            processed += 1
        except Exception:
            continue
    return {"processed": processed, "total": len(memories)}
