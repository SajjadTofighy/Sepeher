"""Deterministic reports over observed operational records."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from ..core import store
from ..intel import shift_report
from ..core.models import ShiftReport

router = APIRouter(route_class=store.StateRoute, tags=["reports"])


@router.get("/api/v1/reports/shift", response_model=ShiftReport)
def shift(from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
          to: Annotated[AwareDatetime | None, Query()] = None):
    return shift_report.snapshot(from_, to)
