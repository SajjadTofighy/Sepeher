import time

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from ..field import device_profiles
from ..core.models import Command, CommandInput, CommandPreview, DeviceProfile
from ..core.store import audit, lookup, now, refresh_commands, state, StateRoute

router = APIRouter(route_class=StateRoute, tags=["commands"])


@router.get("/api/v1/commands", response_model=list[Command])
def commands():
    refresh_commands()
    return list(reversed(state["commands"]))


@router.get("/api/v1/device-profiles", response_model=list[DeviceProfile])
def profiles():
    return device_profiles.catalog()


def sms_fields(asset, command, channel, interval_seconds):
    if channel != "sms":
        return dict(sms_destination=None, sms_text=None)
    return dict(sms_destination=asset["sim"],
                sms_text=device_profiles.render(asset, command, interval_seconds))


@router.get("/api/v1/commands/preview", response_model=CommandPreview)
def preview(asset_id: str, command: Literal["position", "ping", "interval", "restart", "beacon", "diagnostics"],
            channel: Literal["data", "sms"] = "sms", interval_seconds: int = Query(default=30, ge=5, le=3600)):
    a = lookup("assets", asset_id)
    if command not in a["capabilities"]:
        raise HTTPException(422, "فرمان پشتیبانی نمی‌شود")
    return dict(asset_id=asset_id, device_profile=a.get("device_profile", "generic_data"), channel=channel,
                note=device_profiles.NOTE, **sms_fields(a, command, channel, interval_seconds))


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
        **sms_fields(a, p.command, p.channel, p.interval_seconds),
        device_profile=a.get("device_profile", "generic_data"),
        gateway="none",
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
