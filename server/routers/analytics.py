from auth import require_admin
from db import get_db
from fastapi import APIRouter, Depends
from feature_services import attach_categories, list_memories, request_analytics
from models import Category, MemoryCategory, WebhookDelivery
from server_state import get_memory_instance
from sqlalchemy import func, select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
def get_analytics(_auth=Depends(require_admin), db: Session = Depends(get_db)):
    memories = attach_categories(db, list_memories(get_memory_instance()))
    category_rows = (
        db.execute(
            select(Category.name, Category.color, func.count(MemoryCategory.id))
            .join(MemoryCategory, MemoryCategory.category_id == Category.id, isouter=True)
            .group_by(Category.id)
            .order_by(Category.name)
        )
        .all()
    )
    webhook_rows = db.execute(select(WebhookDelivery.status, func.count(WebhookDelivery.id)).group_by(WebhookDelivery.status)).all()
    return {
        **request_analytics(db),
        "total_memories": len(memories),
        "categorized_memories": len([memory for memory in memories if memory.get("categories")]),
        "category_distribution": [
            {"name": name, "color": color, "count": count} for name, color, count in category_rows
        ],
        "webhook_deliveries": [{"status": status, "count": count} for status, count in webhook_rows],
    }
