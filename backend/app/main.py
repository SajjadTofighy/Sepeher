"""Local operational demo with authenticated, durable field operations. No hardware or LLM connection."""

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import AwareDatetime
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi

from .models import Alert, Asset, AuditRecord, AuditVerification, Bootstrap, DeviceEventInput, Summary, TrackPoint
from .seed import seed
from .intel import worker
from .intel.worker import lifespan
from .store import StateRoute
from .auth import IdentityMiddleware, current_principal
from . import authz

app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    title="Sepehr Command — Mock API",
    version="1.0.0",
    description="OIDC-authenticated field operations and audit in SQLite; legacy operational demo in memory, single worker. No hardware access.",
)
app.router.route_class = StateRoute
app.add_middleware(IdentityMiddleware)
from .store import audit, lookup, now, refresh_commands, refresh_tracks, state, summary
from . import sim, store


@app.get("/docs", include_in_schema=False)
def api_docs():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Sepehr API",
        swagger_js_url="/swagger/swagger-ui-bundle.js",
        swagger_css_url="/swagger/swagger-ui.css",
        swagger_favicon_url="/favicon.svg",
    )


@app.get("/api/v1/health")
def health():
    return dict(status="ok", mode="mock", time=now())


@app.get("/api/v1/bootstrap", response_model=Bootstrap)
def bootstrap():
    refresh_commands()
    refresh_tracks()
    return {
        **state,
        "assets": [authz.legacy_asset(asset) for asset in state["assets"]],
        "audit": list(reversed(state["audit"])) if current_principal.get() and "auditor" in current_principal.get().roles else [],
        "summary": summary(),
        "meta": dict(mode="mock", map="openstreetmap", phase="all-demo", time=now()),
    }


@app.get("/api/v1/assets", response_model=list[Asset])
def assets():
    refresh_tracks()
    return [authz.legacy_asset(asset) for asset in state["assets"]]


@app.get("/api/v1/assets/{id}/track", response_model=list[TrackPoint])
def track(id: str, since: AwareDatetime | None = None, until: AwareDatetime | None = None, limit: int = Query(default=500, ge=1, le=10000)):
    lookup("assets", id)
    if since and until and since > until:
        raise HTTPException(422, "شروع بازه باید قبل از پایان آن باشد")
    audit("مشاهده تاریخچه موقعیت", id)
    return store.tracks.read(id, since=since, until=until, limit=limit)


@app.get("/api/v1/analytics", response_model=Summary)
def analytics():
    return summary()


@app.get("/api/v1/audit", response_model=list[AuditRecord])
def audits():
    return list(reversed(state["audit"]))


@app.get("/api/v1/audit/verify", response_model=AuditVerification, response_model_exclude_none=True)
def verify():
    authz.require("audit")
    durable = store.field.audits()
    return dict(
        valid=store.field.verify_audit() and durable == state["audit"],
        count=len(durable),
        scope="persistent SQLite chain and memory cache; not WORM storage",
    )


@app.post("/api/v1/demo/scenario")
def scenario():
    from .routers.positions import ingest_event

    result = ingest_event("AST-010", DeviceEventInput(type="sos", time=now()))
    audit("شروع سناریوی نمایشی", result["event"]["id"])
    return result["incidents"][0] if result["incidents"] else result


STORY_ASSET = "AST-S73"
STORY_POLICY = "POL-01"


@app.get("/api/v1/alerts", response_model=list[Alert])
def alerts():
    refresh_tracks()
    return state["alerts"]


@app.post("/api/v1/demo/story", status_code=201)
def story():
    """Design appendix, step 2: an organisational tracker without a night permit drives
    into the protected zone at the scenario clock 23:10; the policy engine detects it."""
    policy = lookup("policies", STORY_POLICY)
    if policy["status"] not in ("shadow", "active"):
        raise HTTPException(409, "سیاست ورود به محدوده باید در حالت سایه یا فعال باشد")
    zone = lookup("zones", policy["zone"])
    state["assets"] = [a for a in state["assets"] if a["id"] != STORY_ASSET]
    state.get("engine", {}).get("inside", {}).pop(STORY_ASSET, None)
    lons, lats = [p[0] for p in zone["points"]], [p[1] for p in zone["points"]]
    target = [sum(lons) / len(lons) + 0.03, sum(lats) / len(lats) - 0.01]
    start = [max(lons) + 0.025, target[1] + 0.006]
    asset = dict(
        id=STORY_ASSET,
        name="خودروی سازمانی ۷۳",
        kind="vehicle",
        unit="org",
        authorized=False,
        synthetic=True,
        scenario_clock="23:10",
        status="online",
        lon=start[0],
        lat=start[1],
        speed=0,
        battery=88,
        signal=3,
        field="آغاجاری",
        mission="تردد اداری · بدون مجوز شبانه",
        operator="راننده نمونه",
        sim="09•• ••• 7300",
        carrier="همراه اول",
        firmware="2.4.1",
        last_seen=now(),
        capabilities=["position", "ping", "interval", "beacon", "diagnostics"],
        track=[],
    )
    t = time.time()
    plan = sim.new_plan(asset, start, now=t)
    plan.update(t0=t, routes=[{"from": start, "to": target, "start": t, "duration": 18.0, "display_kmh": 62}])
    state.setdefault("sim", {})[STORY_ASSET] = plan
    state["assets"].append(asset)
    store.refresh_track(asset)
    audit("شروع سناریوی نمایش پنج‌دقیقه‌ای", STORY_ASSET, policy["id"])
    return dict(asset_id=STORY_ASSET, zone_id=zone["id"], policy_id=policy["id"], arrives_in=18)


@app.post("/api/v1/demo/reset")
def reset():
    state.clear()
    state.update(seed())
    store.restore_field_state()
    store.begin_data_epoch(now())
    worker.tick(now())
    audit("راه‌اندازی داده‌های نمایشی", "DEMO")
    return dict(ok=True)


@app.get("/api/v1/events")
async def events():
    async def generate():
        while True:
            with store.locked_state():
                refresh_commands()
                message = "data: " + json.dumps(dict(time=now(), summary=summary())) + "\n\n"
            yield message
            await asyncio.sleep(3)

    return StreamingResponse(generate(), media_type="text/event-stream")


from .routers import assistant, commands, configuration, incidents, intel, missions, policies, positions, reports

for module in (incidents, commands, policies, missions, assistant, configuration, positions, intel, reports):
    app.include_router(module.router)

from .routers import field
from .routers import stations
from .routers import schedules
from .routers import field_safety
from .routers import offline
from .routers import field_comms
app.include_router(field_comms.upload_router)
app.include_router(field_comms.router)
app.include_router(stations.router)
app.include_router(schedules.router)
app.include_router(field_safety.router)
app.include_router(offline.router)
app.include_router(field.router)
app.include_router(field.auth_router)


def secured_openapi():
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        for path, methods in schema["paths"].items():
            if path not in ("/api/v1/health", "/api/v1/auth/config") and authz.protected(path):
                for method, operation in methods.items():
                    if method in ("get", "post", "put", "patch", "delete"):
                        operation["security"] = [{"HTTPBearer": []}]
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = secured_openapi

store.restore_field_state()
store.begin_data_epoch()
audit("شروع شیفت نمایشی", "SHIFT-03")
audit("بارگذاری بسته سیاست آغاجاری", "POLICY-PACK")
dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="static")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API route not found")
        candidate = (dist / path).resolve()
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
