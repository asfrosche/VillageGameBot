from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_db

router = APIRouter(tags=["overview"])


@router.get("/api/overview")
async def overview(db=Depends(get_db)):
    return db.get_overview()
