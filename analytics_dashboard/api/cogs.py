from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_db

router = APIRouter(tags=["cogs"])


@router.get("/api/cogs")
async def cog_stats(db=Depends(get_db)):
    return {"items": db.get_cog_stats()}
