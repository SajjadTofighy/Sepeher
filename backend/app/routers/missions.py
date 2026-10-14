from fastapi import APIRouter, HTTPException

from ..models import Mission
from ..store import audit, lookup, state, StateRoute, update_mission_progress, now

router = APIRouter(route_class=StateRoute, tags=["missions"])


@router.get("/api/v1/missions", response_model=list[Mission])
def missions():
    return state["missions"]


@router.post("/api/v1/missions/{id}/checkpoint", response_model=Mission)
def checkpoint(id: str):
    m = lookup("missions", id)
    cp = next((c for c in m["checkpoints"] if not c["visited"]), None)
    if not cp:
        raise HTTPException(409, "همه ایستگاه‌ها ثبت شده‌اند")
    if cp.get("target_id"):
        raise HTTPException(409, "بازدید ایستگاه برنامه‌ریزی‌شده باید از پوشش گشت در مهلت ثبت شود")
    cp["visited"] = True
    cp["visited_at"] = now()
    update_mission_progress(m)
    audit("ثبت ایستگاه گشت", id, cp["name"])
    return m
