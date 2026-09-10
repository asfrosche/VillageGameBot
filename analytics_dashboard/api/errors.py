from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_db

router = APIRouter(tags=["errors"])


@router.get("/api/errors")
async def list_errors(
    command_name: str | None = Query(None),
    limit: int = Query(50),
    db=Depends(get_db),
):
    return {"items": db.get_errors(command_name=command_name, limit=limit)}


@router.get("/api/errors/summary")
async def error_summary(db=Depends(get_db)):
    return db.get_error_summary()
