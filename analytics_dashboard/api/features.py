from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_db

router = APIRouter(tags=["features"])


@router.get("/api/features")
async def feature_health(
    filter: str = Query("all"),
    sort: str = Query("health_score"),
    order: str = Query("asc"),
    db=Depends(get_db),
):
    items = db.get_feature_health()
    if filter == "dead":
        items = [i for i in items if i["health_score"] < 20]
    elif filter == "deprecated":
        items = [i for i in items if 20 <= i["health_score"] < 40]
    elif filter == "review":
        items = [i for i in items if 40 <= i["health_score"] < 60]
    elif filter == "monitor":
        items = [i for i in items if 60 <= i["health_score"] < 80]
    elif filter == "keep":
        items = [i for i in items if i["health_score"] >= 80]
    elif filter == "unused_30":
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        items = [i for i in items if i["last_used"] is None or i["last_used"] < cutoff]
    elif filter == "unused_90":
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()
        items = [i for i in items if i["last_used"] is None or i["last_used"] < cutoff]
    elif filter == "low_usage":
        items = [i for i in items if i["total_execs"] < 10]

    reverse = order == "desc"
    items.sort(key=lambda x: x.get(sort, 0) or 0, reverse=reverse)
    return {"items": items}
