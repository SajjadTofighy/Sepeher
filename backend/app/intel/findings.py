"""Evidence-bearing findings with persistent-condition latches and human-only actions."""

import json
from fastapi import HTTPException

from .. import store
from ..engine import route_incident, routing_decision
from ..models import Finding, FindingEvidence


def _latch_key(rule_id, subject_ids):
    return json.dumps([rule_id, sorted(set(subject_ids))], ensure_ascii=False)


def _route(finding, stamp, zone_id, policy_id=None):
    key = _latch_key(finding["rule_id"], finding["subject_ids"])
    subject_id = finding["subject_ids"][0]
    collection = next((name for name in ("assets", "facilities", "pipelines", "segments", "cameras")
                       if any(row["id"] == subject_id for row in store.state[name])), None)
    if collection is None:
        raise HTTPException(404, "موضوع یافته برای تشکیل پرونده پیدا نشد")
    subject = store.lookup(collection, subject_id)
    asset = subject if "lon" in subject else {
        **subject, "name": subject.get("name", subject_id),
        "lon": subject["points"][0][0], "lat": subject["points"][0][1],
    }
    if collection == "segments":
        geometry = finding["evidence"]["values"]["geometry"]
        asset.update(lon=geometry["coordinates"][0], lat=geometry["coordinates"][1])
    zone = store.lookup("zones", zone_id)["name"] if zone_id else subject.get("field", subject.get("zone", subject_id))
    return route_incident(
        store.state, asset, stamp, store.create_incident,
        dedupe_key=dict(finding_latch_key=key),
        duplicate_action="یافته تکراری در همین پرونده ادغام شد", actor="موتور هوشمندی",
        title=finding["summary"], severity=finding["severity"], zone=zone, zone_id=zone_id,
        description=f"{finding['summary']} · یافته {finding['id']} · قاعده {finding['rule_id']}",
        first_action="ثبت یافته مستند؛ بررسی و هر اقدام با تأیید انسان",
        policy_id=policy_id,
    )["id"]


@store.state_locked
def raise_finding(*, rule_id, kind, subject_ids, summary, evidence, sources,
                  severity="medium", mode="shadow", needs_incident=False,
                  action="create_incident", zone_id=None, now_iso=None, policy_id=None):
    """A persistent condition creates one finding until resolve_finding clears it."""
    key = _latch_key(rule_id, subject_ids)
    latches = store.state["intel"]["latches"]
    if key in latches:
        return store.lookup("findings", latches[key])
    stamp = now_iso or store.now()
    decision = routing_decision(store.state["settings"], mode, action)
    item = Finding(
        id=f"FND-{len(store.state['findings']) + 1:04}", kind=kind, rule_id=rule_id,
        severity=severity, mode=decision["mode"], created_at=stamp, updated_at=stamp,
        subject_ids=subject_ids, summary=summary, evidence=FindingEvidence.model_validate(evidence),
        sources=sources,
    ).model_dump(mode="json")
    if needs_incident and decision["routed"]:
        item["incident_id"] = _route(item, stamp, zone_id, policy_id)
    store.state["findings"].insert(0, item)
    latches[key] = item["id"]
    store.audit("ایجاد یافته هوشمندی", item["id"], f"{rule_id} · {item['mode']} · {decision['reason']}")
    return item


@store.state_locked
def resolve_finding(id, now_iso=None):
    item = store.lookup("findings", id)
    if item["status"] != "resolved":
        item.update(status="resolved", updated_at=now_iso or store.now())
        key = _latch_key(item["rule_id"], item["subject_ids"])
        latches = store.state["intel"]["latches"]
        if latches.get(key) == id:
            del latches[key]
        store.audit("رفع یافته هوشمندی", id, item["rule_id"])
    return item


@store.state_locked
def acknowledge(id, now_iso=None):
    item = store.lookup("findings", id)
    if item["status"] == "resolved":
        raise HTTPException(409, "یافته رفع‌شده قابل تأیید دریافت نیست")
    if item["status"] == "open":
        item.update(status="acknowledged", updated_at=now_iso or store.now())
        store.audit("تأیید دریافت یافته هوشمندی", id, item["rule_id"])
    return item
