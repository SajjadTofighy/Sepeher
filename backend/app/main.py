"""Local operational demo with authenticated, durable field operations. No hardware or LLM connection."""

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import AwareDatetime
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi

from .core.models import Alert, Asset, AuditRecord, AuditVerification, Bootstrap, DeviceEventInput, Summary, TrackPoint, PositionObservation
from .core.models import ChangeSet, MapFeatureResult, TrackBatch
from .core import journal
from .core.seed import seed
from .intel import worker
from .intel.worker import lifespan
from .core.store import StateRoute
from .security.auth import IdentityMiddleware, current_principal
from .security import authz

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


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Echo neither submitted values, internal context nor documentation URLs.
    return JSONResponse(status_code=422, content={"detail": [
        dict(loc=[str(part) for part in item["loc"]], msg=item["msg"], type=item["type"]) for item in error.errors()]})
from .core.store import audit, lookup, now, refresh_commands, refresh_tracks, state, summary
from .core import sim, store


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
async def health():
    # Liveness must not wait on the state lock: a slow handler would otherwise fail the probe
    # and get a healthy process restarted.
    return dict(status="ok", mode="mock", time=now())


BOOTSTRAP_AUDIT = 500


@app.get("/api/v1/bootstrap", response_model=Bootstrap)
def bootstrap():
    # Sync first, under the same lock as the snapshot: the cursor covers exactly this state.
    feed = journal.journal
    feed.sync(force=True)
    points = state["settings"]["map_trail_points"]
    auditor = current_principal.get() and "auditor" in current_principal.get().roles
    return {
        **state,
        "assets": [authz.legacy_asset(journal.trail(asset, points)) for asset in state["assets"]],
        # Recent audit only; the full chain is paged from /api/v1/audit.
        "audit": list(reversed(state["audit"][-BOOTSTRAP_AUDIT:])) if auditor else [],
        "summary": summary(),
        "meta": dict(mode="mock", map="openstreetmap", phase="all-demo", time=now(), cursor=feed.cursor(),
                     audit_total=str(len(state["audit"])) if auditor else "0"),
    }


def change_set(cursor):
    """Changes after a cursor, projected for the current principal (identity fields stay hidden)."""
    feed = journal.journal
    rows, next_cursor, reset = feed.since(cursor)
    result = dict(cursor=next_cursor, reset=reset, removed={}, summary=None, server_time=now(),
                  **{kind: [] for kind in journal.COLLECTIONS})
    latest = {}
    for seq, kind, id, view in rows:
        latest[(kind, id)] = view  # the newest entry per entity wins
    for (kind, id), view in latest.items():
        if kind == "summary":
            result["summary"] = view
        elif view is None:
            result["removed"].setdefault(kind, []).append(id)
        else:
            result[kind].append(authz.legacy_asset(view) if kind == "assets" else view)
    return result


# Long-poll timing hooks (injected in tests; never patch the shared asyncio/time modules).
poll_clock = time.monotonic
poll_sleep = asyncio.sleep


@app.get("/api/v1/changes", response_model=ChangeSet)
async def changes(cursor: str = Query(min_length=1, max_length=64), wait: float = Query(default=0, ge=0, le=25)):
    """Long-poll the live picture: returns as soon as something changed, or after ``wait`` seconds."""
    deadline = poll_clock() + wait
    while True:
        await asyncio.to_thread(journal.journal.sync)
        rows, _, reset = journal.journal.since(cursor, limit=1)
        if rows or reset or poll_clock() >= deadline:
            return await asyncio.to_thread(change_set, cursor)
        await poll_sleep(0.25)


@app.get("/api/v1/map/features", response_model=MapFeatureResult)
def map_features(bbox: str = Query(pattern=r"^-?\d+(\.\d+)?(,-?\d+(\.\d+)?){3}$"),
                 layers: str = Query(default="assets,incidents,facilities", max_length=100),
                 limit: int = Query(default=500, ge=1, le=5000)):
    """Bounded spatial query: features inside lon/lat bbox (WGS84, lon first), capped by limit."""
    west, south, east, north = map(float, bbox.split(","))
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise HTTPException(422, "محدوده bbox باید به ترتیب غرب،جنوب،شرق،شمال و معتبر باشد")
    wanted = set(layers.split(","))
    if not wanted <= {"assets", "incidents", "facilities"}:
        raise HTTPException(422, "لایه درخواستی معتبر نیست")
    refresh_tracks()
    rows = []
    if "assets" in wanted:
        rows += [dict(id=a["id"], layer="assets", name=a["name"], lon=a["lon"], lat=a["lat"], status=a["status"],
                      kind=a["kind"], position_state=a.get("position_state")) for a in state["assets"]]
    if "incidents" in wanted:
        rows += [dict(id=i["id"], layer="incidents", name=i["title"], lon=i["lon"], lat=i["lat"], status=i["status"],
                      severity=i["severity"]) for i in state["incidents"] if i["status"] != "closed"]
    if "facilities" in wanted:
        rows += [dict(id=f["id"], layer="facilities", name=f["name"], lon=f["lon"], lat=f["lat"],
                      status="unmanned" if f.get("unmanned") else "manned") for f in state["facilities"]]
    inside = [r for r in rows if west <= r["lon"] <= east and south <= r["lat"] <= north]
    return dict(features=inside[:limit], total=len(inside), truncated=len(inside) > limit)


TRACK_BATCH_POINTS = 100000


@app.get("/api/v1/tracks", response_model=TrackBatch)
def track_batch(since: AwareDatetime, until: AwareDatetime, asset_id: list[str] = Query(min_length=1, max_length=500),
                limit_per_asset: int = Query(default=2000, ge=1, le=10000)):
    """History for replay over a window, separate from the live picture and capped in total."""
    if since > until:
        raise HTTPException(422, "شروع بازه باید قبل از پایان آن باشد")
    budget, truncated, tracks = TRACK_BATCH_POINTS, False, {}
    for id in dict.fromkeys(asset_id):
        asset = lookup("assets", id)
        source = "reported" if store.observation_source(asset) == "reported" else None
        points = store.tracks.read(id, since=since, until=until, limit=min(limit_per_asset, budget) + 1, source=source)
        if len(points) > min(limit_per_asset, budget):
            truncated, points = True, points[1:]
        tracks[id] = points
        budget -= len(points)
        if budget <= 0:
            truncated = True
            break
    audit("مشاهده تاریخچه موقعیت برای بازپخش", ",".join(tracks)[:200], f"{since.isoformat()}..{until.isoformat()}")
    return dict(tracks=tracks, truncated=truncated)


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
    # Once a real device reports, synthetic seed history is never mixed into its track.
    source = "reported" if store.observation_source(store.lookup("assets", id)) == "reported" else None
    return store.tracks.read(id, since=since, until=until, limit=limit, source=source)


@app.get("/api/v1/assets/{id}/observations", response_model=list[PositionObservation])
def observations(id: str, since: AwareDatetime | None = None, until: AwareDatetime | None = None,
                 limit: int = Query(default=500, ge=1, le=10000)):
    """Raw observations with quality evidence, including points never accepted for live."""
    lookup("assets", id)
    if since and until and since > until:
        raise HTTPException(422, "شروع بازه باید قبل از پایان آن باشد")
    audit("مشاهده شواهد کیفیت موقعیت", id)
    source = "reported" if store.observation_source(store.lookup("assets", id)) == "reported" else None
    return store.tracks.detailed(id, since=since, until=until, limit=limit, source=source)


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
    journal.reset()
    state.clear()
    state.update(seed())
    store.restore_field_state()
    store.begin_data_epoch(now())
    worker.tick(now())
    audit("راه‌اندازی داده‌های نمایشی", "DEMO")
    return dict(ok=True)


@app.get("/api/v1/events")
async def events(request: Request, cursor: str | None = Query(default=None, max_length=64)):
    """SSE of the change journal. Resumes from Last-Event-ID (or ``cursor``); ``reset`` asks for a reload.

    Locked work runs in a worker thread: the event loop must never wait on the state lock.
    """
    start = request.headers.get("last-event-id") or cursor

    async def generate():
        position = start
        if position is None:
            await asyncio.to_thread(journal.journal.sync, True)
            position = journal.journal.cursor()
            yield f"id: {position}\nevent: ready\ndata: {{}}\n\n"
        while not await request.is_disconnected():
            await asyncio.to_thread(journal.journal.sync)
            body = await asyncio.to_thread(change_set, position)
            if body["reset"]:
                yield f"id: {body['cursor']}\nevent: reset\ndata: {{}}\n\n"
                position = body["cursor"]
            elif body["cursor"] != position:
                position = body["cursor"]
                yield f"id: {position}\nevent: changes\ndata: {json.dumps(body, ensure_ascii=False, default=str)}\n\n"
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


from .routers import assistant, commands, configuration, incidents, intel, missions, policies, positions, reports, routing

for module in (incidents, commands, policies, missions, assistant, configuration, positions, intel, reports, routing):
    app.include_router(module.router)

from .routers import field
from .routers import stations
from .routers import schedules
from .routers import field_safety
from .routers import offline
from .routers import field_comms
from .routers import supervision
from .routers import mission_commands
app.include_router(supervision.router)
app.include_router(mission_commands.router)
app.include_router(mission_commands.field_router)
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
