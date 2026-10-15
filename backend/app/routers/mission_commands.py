"""Spatial mission commands: operator preview/send/cancel and the guard's device-bound receipt chain."""
from fastapi import APIRouter, Query, Request, Response

from ..core import store
from ..core.models import (MissionCommand, MissionCommandAction, MissionCommandCancel, MissionCommandInput,
                           MissionCommandPreview, MissionCommandPreviewInput)
from ..field import mission_commands as logic
from ..security import authz
from .field import ERROR_RESPONSES, FieldRoute, device_for

router = APIRouter(route_class=store.StateRoute, tags=["mission-commands"], responses=ERROR_RESPONSES)
field_router = APIRouter(route_class=FieldRoute, tags=["mission-commands"], responses=ERROR_RESPONSES)


@router.post("/api/v1/mission-commands/preview", response_model=MissionCommandPreview)
def preview(payload: MissionCommandPreviewInput):
    return logic.preview(payload.geometry.model_dump(), payload.radius_m)


@router.post("/api/v1/mission-commands", response_model=MissionCommand, status_code=201)
def create(payload: MissionCommandInput, response: Response):
    command, created = logic.create(payload)
    if not created:
        response.status_code = 200  # idempotent replay of the same request
    return command


@router.get("/api/v1/mission-commands", response_model=list[MissionCommand])
def listing(status: str | None = Query(default=None, pattern=r"^(active|dispatched|delivered|acknowledged|in_progress|completed|rejected|failed|expired|cancelled)$")):
    return logic.visible_commands(authz.require("manage"), status)


@router.get("/api/v1/mission-commands/{id}", response_model=MissionCommand)
def detail(id: str):
    principal = authz.require("manage")
    logic.expire_due()
    return logic._view(logic.lookup(id, principal))


@router.post("/api/v1/mission-commands/{id}/cancel", response_model=MissionCommand)
def cancel(id: str, payload: MissionCommandCancel):
    return logic.cancel(id, payload)


@field_router.get("/api/v1/tour/mission-commands", response_model=list[MissionCommand])
def inbox(request: Request):
    principal = authz.require("read")
    return logic.inbox(principal, device_for(request, principal))


@field_router.post("/api/v1/tour/mission-commands/{id}/events", response_model=MissionCommand)
def act(id: str, payload: MissionCommandAction, request: Request):
    principal = authz.require("read")
    return logic.act(id, payload, principal, device_for(request, principal))
