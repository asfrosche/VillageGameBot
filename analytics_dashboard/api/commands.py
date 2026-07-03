from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_db

router = APIRouter(tags=["commands"])


@router.get("/api/commands")
async def list_commands(
    sort: str = Query("total_execs"),
    order: str = Query("desc"),
    search: str = Query(""),
    page: int = Query(1),
    per_page: int = Query(50),
    db=Depends(get_db),
):
    return db.get_commands(sort=sort, order=order, search=search, page=page, per_page=per_page)


@router.get("/api/commands/{name}")
async def command_detail(name: str, db=Depends(get_db)):
    result = db.get_command_detail(name)
    if result is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "Command not found"})
    return result
