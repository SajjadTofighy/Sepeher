from fastapi import APIRouter, HTTPException, Query

from ..core import roads
from ..core.models import RoadNetworkStatus, RoadRoute, RoutePlan, RouteRequest
from ..core.store import StateRoute

router = APIRouter(route_class=StateRoute, tags=["routing"])


@router.get("/api/v1/routing/network", response_model=RoadNetworkStatus)
def network():
    graph = roads.network()
    return dict(source=graph.source, nodes=len(graph.coords), edges=graph.edges, max_snap_km=roads.MAX_SNAP_KM)


@router.get("/api/v1/routing/route", response_model=RoadRoute)
def route(from_lon: float = Query(ge=-180, le=180), from_lat: float = Query(ge=-90, le=90),
          to_lon: float = Query(ge=-180, le=180), to_lat: float = Query(ge=-90, le=90)):
    result = roads.network().route([from_lon, from_lat], [to_lon, to_lat])
    if not result:
        raise HTTPException(404, "مسیر روی شبکه راه یافت نشد؛ یکی از دو نقطه خارج از شبکه یا بدون اتصال است")
    return result


@router.post("/api/v1/routing/routes", response_model=RoutePlan)
def routes(payload: RouteRequest):
    """Fastest route and up to two distinct alternatives that never cross the given closed areas."""
    areas = [area.model_dump() for area in payload.avoid_areas]
    return dict(routes=roads.network().routes(payload.origin, payload.destination, payload.alternatives, areas),
                avoided_areas=len(areas), source=roads.network().source)
