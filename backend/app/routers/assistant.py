"""Rule-based Persian assistant over live records (design §10). No LLM, no command authority:
every answer is assembled from system data and cites the incident records it used."""

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from ..core.tracks import parse_timestamp
from ..core.models import AssistantAnswer, Question, SEVERITY_LABELS as SEVERITY
from ..core.store import state, StateRoute

router = APIRouter(route_class=StateRoute, tags=["assistant"])

RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def asset_name(asset_id):
    return next((a["name"] for a in state["assets"] if a["id"] == asset_id), asset_id)


def answer(text, sources):
    return dict(answer=text, sources=sources, mock=True, can_execute=False)


def explain(incident):
    policy = next((p for p in state["policies"] if p["id"] == incident.get("policy_id")), None)
    text = f"پرونده {incident['id']} با سطح «{SEVERITY[incident['severity']]}» ثبت شده است. "
    if policy:
        text += (
            f"علت: سیاست {policy['id']} «{policy['name']}» (نسخه {policy['version']}) برای ورود به این محدوده "
            f"در بازه {policy['schedule']} سطح «{SEVERITY[policy['severity']]}» تعیین کرده است. "
        )
    text += incident["description"] + " "
    text += f"آخرین اقدام: {incident['timeline'][-1]['action']}."
    return text


@router.post("/api/v1/assistant", response_model=AssistantAnswer)
def assistant(p: Question):
    q = p.question.translate(DIGITS)
    if "گزارش شیفت" in q:
        from ..intel.shift_report import snapshot

        report = snapshot()
        text = " ".join(line["text"] for line in report["headlines"])
        if report["partial"]:
            text += " گزارش جزئی است؛ تاریخچه کامل این بازه در دسترس نیست."
        return answer(text, list(dict.fromkeys(id for line in report["headlines"] for id in line["source_ids"])))
    if "پوشش" in q or "بازدید نشده" in q:
        from ..intel.coverage import snapshot
        from ..core.store import now

        gaps = [row for row in snapshot(now())["items"] if row["status"] != "ok"]
        gaps.sort(key=lambda row: (row["status"] != "never", -(row["age_minutes"] or 0), row["id"]))
        selected = gaps[:5]
        if not selected:
            return answer("همه قطعه‌ها و تأسیسات در مهلت تعیین‌شده بازدید شده‌اند.", [])
        records = {row["id"]: row for key in ("segments", "facilities") for row in state[key]}
        names = [records[row["id"]].get("name") or f"قطعه {records[row['id']]['index'] + 1} از {records[row['id']]['pipeline_id']}" for row in selected]
        ids = {row["id"] for row in selected}
        sources = [f["id"] for f in state["findings"] if f["kind"] == "coverage_gap" and f["status"] != "resolved" and any(id in ids for id in f["subject_ids"])]
        return answer(f"{len(gaps)} قطعه یا تأسیسات نیازمند بازدید است. اولویت‌های پوشش گشت: {'، '.join(names)}.", sources)

    opened = sorted(
        (i for i in state["incidents"] if i["status"] != "closed"),
        key=lambda i: (RANK[i["severity"]], i["created_at"]),
    )

    match = re.search(r"\d{3,}", q)
    if match:
        incident = next((i for i in state["incidents"] if i["id"].endswith(match.group())), None)
        if incident:
            return answer(explain(incident), [incident["id"]])
        return answer(f"پرونده‌ای با شماره {match.group()} در سامانه پیدا نشد.", [])

    if "مسیر" in q:
        rows = [i for i in opened if "مسیر" in i["title"]]
        if not rows:
            return answer("در حال حاضر هیچ گشتی هشدار انحراف از مسیر باز ندارد.", [])
        names = "، ".join(f"{asset_name(i['asset_id'])} ({i['zone']})" for i in rows)
        return answer(f"{len(rows)} هشدار انحراف از مسیر باز است: {names}.", [i["id"] for i in rows])

    if "منطقه" in q and ("بیشترین" in q or "۲۴" in p.question or "24" in q):
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        counts = {}
        for i in state["incidents"]:
            if parse_timestamp(i["created_at"]) >= since:
                counts.setdefault(i["zone"], []).append(i["id"])
        for a in state.get("alerts", []):
            if not a["routed"]:
                counts.setdefault(a["zone"], []).append(a["id"])
        if not counts:
            return answer("در ۲۴ ساعت گذشته هشداری ثبت نشده است.", [])
        zone, ids = max(counts.items(), key=lambda kv: len(kv[1]))
        return answer(
            f"در ۲۴ ساعت گذشته «{zone}» با {len(ids)} هشدار و حادثه بیشترین رخداد را داشته است "
            f"(هشدارهای حالت سایه هم شمرده شده‌اند).",
            [x for x in ids if x.startswith("INC-")],
        )

    if "ارتباط" in q or "قطع" in q:
        offline = [a for a in state["assets"] if a["status"] == "offline"]
        rows = [i for i in opened if "ارتباط" in i["title"]]
        text = f"{len(offline)} تجهیز قطع ارتباط دارد"
        text += ": " + "، ".join(a["name"] for a in offline) + "." if offline else "."
        if rows:
            text += f" پرونده {rows[0]['id']} در {rows[0]['zone']} برای آن باز است؛ آستانه قطع ارتباط به پوشش منطقه وابسته است."
        return answer(text, [i["id"] for i in rows])

    if not opened:
        return answer("در حال حاضر پرونده بازی وجود ندارد. همه گشت‌ها در وضعیت عادی‌اند.", [])
    top = opened[0]
    critical = [i for i in opened if i["severity"] == "critical"]
    text = f"{len(opened)} پرونده باز است که {len(critical)} مورد بحرانی است. مهم‌ترین: {top['id']} «{top['title']}» در {top['zone']}"
    if top.get("assigned_to"):
        text += f"؛ {asset_name(top['assigned_to'])} اعزام شده است."
    else:
        text += "؛ هنوز گشتی اعزام نشده است. پیش از اعزام، نزدیک‌ترین گشت و مجوز ورود بررسی شود."
    return answer(text, [i["id"] for i in opened[:3]])
