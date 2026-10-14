import time

from fastapi import APIRouter, HTTPException

from ..models import Command, CommandInput
from ..store import audit, lookup, now, refresh_commands, state, StateRoute

router = APIRouter(route_class=StateRoute, tags=["commands"])


@router.get("/api/v1/commands", response_model=list[Command])
def commands():
    refresh_commands()
    return list(reversed(state["commands"]))


@router.post("/api/v1/commands", status_code=201, response_model=Command)
def command(p: CommandInput):
    existing = next(
        (c for c in state["commands"] if c["request_id"] == p.request_id), None
    )
    if existing:
        if any(existing[k] != v for k, v in p.model_dump().items()):
            raise HTTPException(
                409, "شناسه درخواست قبلاً برای فرمان دیگری استفاده شده است"
            )
        return existing
    a = lookup("assets", p.asset_id)
    if p.command not in a["capabilities"]:
        raise HTTPException(422, "فرمان پشتیبانی نمی‌شود")
    c = dict(
        **p.model_dump(),
        id=f"CMD-{len(state['commands']) + 1001}",
        status="sent",
        created_at=now(),
        updated_at=now(),
        epoch=time.time(),
        timeout_seconds=20 if p.channel == "sms" else 10,
        actor="اپراتور نمایشی",
        mock=True,
    )
    state["commands"].append(c)
    audit("صدور فرمان نمایشی", c["id"], p.command)
    return c
