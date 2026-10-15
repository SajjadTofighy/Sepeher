"""Communication-gap layer from real reception evidence; explainable, shadow findings only.

Two kinds of evidence per grid cell (local metric grid via geo.project_m):
* offline_samples: positions observed on time but received later than the observation gap
  (queued while the network was down) - positive evidence of no network at that place;
* silences: no observation for longer than the gap; cause unknown (power, fix or network),
  attributed to where the silence began.
Cells with too few samples are labelled low confidence; nothing is inferred from silence alone.
"""
from datetime import timedelta
import math

from ..core import store
from ..core.engine import observation_gap_seconds
from ..core.tracks import parse_timestamp
from . import geo
from .findings import raise_finding

RULE_ID = "intel.comm_gap"


def layer(hours=24, cell_m=500, now=None):
    now = now or store.now()
    until = parse_timestamp(now)
    since = until - timedelta(hours=hours)
    ref_lat = store.state["assets"][0]["lat"] if store.state["assets"] else 30.0
    cells = {}

    def cell(lon, lat):
        x, y = geo.project_m([lon, lat], ref_lat)
        key = (math.floor(x / cell_m), math.floor(y / cell_m))
        return cells.setdefault(key, dict(samples=0, offline=0, silences=0, minutes=0.0, assets=set(), pts=[]))

    for asset in store.state["assets"]:
        if store.observation_source(asset) != "reported":
            continue
        gap = observation_gap_seconds(asset)
        rows = store.tracks.detailed(asset["id"], since=since, until=until, limit=20000, source="reported")
        for previous, row in zip([None, *rows], rows):
            c = cell(row["lon"], row["lat"])
            c["samples"] += 1
            c["assets"].add(asset["id"])
            c["pts"].append((row["lon"], row["lat"]))
            if row["received_at"] and (parse_timestamp(row["received_at"]) - parse_timestamp(row["time"])).total_seconds() > gap:
                c["offline"] += 1
            if previous:
                silent = (parse_timestamp(row["time"]) - parse_timestamp(previous["time"])).total_seconds()
                if silent > gap:
                    start = cell(previous["lon"], previous["lat"])
                    start["silences"] += 1
                    start["minutes"] += silent / 60
    threshold = store.state["settings"]["intel_comm_gap_min_events"]
    out = []
    for key, c in cells.items():
        lon = sum(p[0] for p in c["pts"]) / len(c["pts"]) if c["pts"] else 0
        lat = sum(p[1] for p in c["pts"]) / len(c["pts"]) if c["pts"] else 0
        id = f"cell:{cell_m}:{key[0]}:{key[1]}"
        events = c["offline"] + c["silences"]
        finding_id = None
        if events >= threshold:
            finding = raise_finding(
                rule_id=RULE_ID, kind="communication_gap", severity="info", subject_ids=[id],
                summary=f"شکاف ارتباطی مکرر در سلول {key[0]}،{key[1]}", sources=sorted(c["assets"]), now_iso=now,
                evidence=dict(rule="رکورد دیررس صف آفلاین یا سکوت بیش از فاصله مشاهده", thresholds=dict(
                    min_events=threshold, cell_m=cell_m, hours=hours), window_from=since.isoformat(), window_to=now,
                    points=[[lon, lat, now]], values=dict(samples=c["samples"], offline_samples=c["offline"],
                                                          silences=c["silences"], silence_minutes=round(c["minutes"], 1))))
            finding_id = finding["id"]
        out.append(dict(id=id, lon=lon, lat=lat, cell_m=cell_m, samples=c["samples"], offline_samples=c["offline"],
                        silences=c["silences"], silence_minutes=round(c["minutes"], 1), assets=len(c["assets"]),
                        confidence="low" if c["samples"] < 20 else "medium", finding_id=finding_id))
    return dict(cells=sorted(out, key=lambda r: -(r["offline_samples"] + r["silences"])), window_from=since.isoformat(),
                window_to=now, method="سلول شبکه متریک؛ رکورد دیررس صف آفلاین = نبود شبکه؛ سکوت = علت نامعلوم (خاموشی، نبود fix یا شبکه)")
