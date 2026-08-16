"""Backup management endpoints.

Backups are admin-only: a dump contains every memory in the instance, and a
restore destroys current state.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import backup_services
from auth import require_admin
from db import SessionLocal, get_db

router = APIRouter(prefix="/backups", tags=["backups"])
logger = logging.getLogger(__name__)


class RestoreRequest(BaseModel):
    # Restores are irreversible, so the client must say so explicitly rather
    # than a stray POST being enough to wipe the instance.
    confirm: bool = Field(..., description="Must be true to proceed.")


@router.get("")
def list_backups(
    limit: int = Query(default=50, ge=1, le=200),
    _admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    # Fold in any runs abandoned by a killed process before listing, so the UI
    # never shows a backup stuck at "running" forever.
    backup_services.sweep_stale_runs(db)
    return {
        "backups": [backup_services.serialize(row) for row in backup_services.list_backups(db, limit)],
        "retention_count": backup_services.RETENTION_COUNT,
        "missing_tools": backup_services.missing_tools(),
        "directory": str(backup_services.BACKUP_DIR),
    }


@router.post("", status_code=201)
async def create_backup(_admin=Depends(require_admin)):
    """Run a backup now.

    pg_dump is blocking and can run for minutes, so it goes to a worker thread
    with its own session; holding the request's pooled connection open for the
    whole dump would starve the pool.
    """
    missing = backup_services.missing_tools()
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Backups are unavailable: {', '.join(missing)} not found in this image. "
                "Rebuild the API image with the Postgres client tools installed."
            ),
        )

    def _run():
        with SessionLocal() as session:
            return backup_services.serialize(backup_services.run_backup(session, kind="manual"))

    try:
        return await asyncio.get_running_loop().run_in_executor(None, _run)
    except backup_services.BackupError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{backup_id}/download")
def download_backup(
    backup_id: uuid.UUID,
    part: str = Query(default="vector", pattern="^(vector|app)$"),
    _admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    from models import Backup

    record = db.get(Backup, backup_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Backup not found.")
    if record.status != "completed":
        raise HTTPException(status_code=409, detail="Backup did not complete.")
    try:
        path = backup_services.resolve_backup_path(f"{record.filename}.{part}")
    except backup_services.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup file is missing from disk.")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/{backup_id}/restore")
async def restore_backup(
    backup_id: uuid.UUID,
    body: RestoreRequest,
    _admin=Depends(require_admin),
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Restore must be confirmed.")

    def _run():
        with SessionLocal() as session:
            backup_services.restore_backup(session, backup_id)

    try:
        await asyncio.get_running_loop().run_in_executor(None, _run)
    except backup_services.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Restore complete. Restart the API so cached state is rebuilt."}


@router.delete("/{backup_id}", status_code=204)
def delete_backup(
    backup_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        backup_services.delete_backup(db, backup_id)
    except backup_services.BackupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
