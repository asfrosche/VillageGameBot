from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_db

router = APIRouter(tags=["performance"])


@router.get("/api/performance/slowest")
async def slowest_commands(limit: int = Query(25), db=Depends(get_db)):
    return {"items": db.get_slowest_commands(limit=limit)}


@router.get("/api/performance/over-time")
async def performance_over_time(days: int = Query(30), db=Depends(get_db)):
    return {"items": db.get_performance_over_time(days=days)}


@router.get("/api/performance/summary")
async def performance_summary(db=Depends(get_db)):
    cmds = db.get_commands(sort="total_execs", order="desc", per_page=1000)
    items = cmds["items"]
    if not items:
        return {"items": []}
    sorted_by_avg = sorted(items, key=lambda x: x["avg_time_ms"], reverse=True)
    return {
        "items": [
            {
                "command_name": c["command_name"],
                "cog_name": c["cog_name"],
                "avg_time_ms": c["avg_time_ms"],
                "p50_ms": c["p50_ms"],
                "p95_ms": c["p95_ms"],
                "p99_ms": c["p99_ms"],
                "max_duration": c["max_duration"],
                "total_execs": c["total_execs"],
            }
            for c in sorted_by_avg[:25]
        ]
    }
