"""Shared layer ingestion, findings and registered intelligence capabilities."""

from typing import Literal

from fastapi import APIRouter, HTTPException

from .. import store
from ..intel import coverage, findings, safety, hazard, risk, patrol
from ..intel import ingest
from ..intel.geo import derive_segments
from ..models import Coverage, Finding, HazardStatus, LayerImport, LayerImportResult, LineFeature, PatrolPlan, PatrolPlanInput, RiskStatus, SafetyConfirmation, SafetyEpisode, SafetyStatus, Segment
from ..models import PipelinePressureInput, PipelinePressureResult, PlateReadInput, PlateReadResult

router = APIRouter(route_class=store.StateRoute, tags=["intel"])


@router.post("/api/v1/intel/ingest/pipeline-pressure", response_model=PipelinePressureResult, status_code=201)
def pipeline_pressure(payload: PipelinePressureInput):
    return ingest.pipeline_pressure(payload)


@router.post("/api/v1/intel/ingest/plate-read", response_model=PlateReadResult, status_code=201)
def plate_read(payload: PlateReadInput):
    return ingest.plate_read(payload)


@router.get("/api/v1/intel/segments", response_model=list[Segment])
def segments():
    return store.state["segments"]


@router.post("/api/v1/intel/layers/import", response_model=LayerImportResult, status_code=201)
def import_layers(payload: LayerImport):
    pipelines, facilities = [], []
    fields = {asset["field"] for asset in store.state["assets"]}
    used_ids = {row["id"] for name in ("pipelines", "facilities", "segments", "assets") for row in store.state[name]}
    for feature in payload.features:
        properties = feature.properties.model_dump(exclude={"id"})
        if properties["field"] not in fields:
            raise HTTPException(422, "نام میدان باید یکی از میدان‌های موجود باشد")
        line = isinstance(feature, LineFeature)
        prefix = "PIPE" if line else "FAC"
        collection = pipelines if line else facilities
        index = len(store.state["pipelines" if line else "facilities"]) + len(collection) + 1
        id = feature.properties.id
        if id is None:
            while f"{prefix}-{index:03}" in used_ids:
                index += 1
            id = f"{prefix}-{index:03}"
        if id in used_ids:
            raise HTTPException(409, "شناسه لایه تکراری است")
        used_ids.add(id)
        if line:
            collection.append(dict(id=id, **properties, points=feature.geometry.coordinates))
        else:
            lon, lat = feature.geometry.coordinates
            collection.append(dict(id=id, **properties, lon=lon, lat=lat))
    # Validate and derive everything before changing state: imports are atomic.
    derived = derive_segments(pipelines)
    if any(segment["id"] in used_ids for segment in derived):
        raise HTTPException(409, "شناسه قطعه مشتق‌شده با رکورد موجود تداخل دارد")
    store.state["pipelines"].extend(pipelines)
    store.state["facilities"].extend(facilities)
    store.state["segments"].extend(derived)
    store.state["intel"].pop("coverage", None)
    store.audit("ورود لایه‌های هوشمندی", "INTEL-LAYERS", f"{len(pipelines)} خط · {len(facilities)} تأسیسات · {len(derived)} قطعه")
    return dict(pipelines=pipelines, facilities=facilities, segments=derived)


@router.get("/api/v1/intel/findings", response_model=list[Finding])
def list_findings(kind: str | None = None, status: Literal["open", "acknowledged", "resolved"] | None = None):
    return [item for item in store.state["findings"]
            if (kind is None or item["kind"] == kind) and (status is None or item["status"] == status)]


@router.post("/api/v1/intel/findings/{id}/ack", response_model=Finding)
def acknowledge_finding(id: str):
    return findings.acknowledge(id)


@router.get("/api/v1/intel/coverage", response_model=Coverage)
def patrol_coverage():
    return coverage.snapshot(store.now())


@router.get("/api/v1/intel/safety", response_model=SafetyStatus)
def patrol_safety():
    return safety.snapshot()


@router.post("/api/v1/intel/safety/{asset_id}/confirm", response_model=SafetyEpisode)
def confirm_safety(asset_id: str, payload: SafetyConfirmation):
    return safety.confirm(asset_id, payload.note)


@router.get("/api/v1/intel/hazard/{incident_id}", response_model=HazardStatus)
def incident_hazard(incident_id: str):
    return hazard.snapshot(incident_id)


@router.get("/api/v1/intel/risk", response_model=RiskStatus)
def risk_scores():
    return risk.snapshot()


@router.get("/api/v1/intel/patrol-plans", response_model=list[PatrolPlan])
def patrol_plans():
    return store.state["patrol_plans"]


@router.get("/api/v1/intel/patrol-plans/{id}", response_model=PatrolPlan)
def patrol_plan(id: str):
    return store.lookup("patrol_plans", id)


@router.post("/api/v1/intel/patrol-plans", response_model=PatrolPlan, status_code=201)
def create_patrol_plan(payload: PatrolPlanInput):
    return patrol.create(payload)


@router.post("/api/v1/intel/patrol-plans/{id}/approve", response_model=PatrolPlan)
def approve_patrol_plan(id: str):
    return patrol.approve(id)


@router.post("/api/v1/intel/patrol-plans/{id}/discard", response_model=PatrolPlan)
def discard_patrol_plan(id: str):
    return patrol.discard(id)
