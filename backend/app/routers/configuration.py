"""Mock configuration and GIS records. No external service connections."""

from urllib.parse import urlsplit
import os

from fastapi import APIRouter, HTTPException

from ..core.models import Asset, CameraEventInput, PlateReadInput, PlateReadResult, RuntimeSettings, Zone, ZoneInput, AssetSettings, Camera
from ..core.store import audit, lookup, state, StateRoute
from ..security.authz import legacy_asset

router = APIRouter(route_class=StateRoute, tags=["configuration"])


@router.get("/api/v1/zones", response_model=list[Zone])
def zones():
    return state["zones"]


@router.post("/api/v1/zones", response_model=Zone, status_code=201)
def create_zone(p: ZoneInput):
    z = dict(**p.model_dump(), id=f"Z{len(state['zones']) + 1}")
    state["zones"].append(z)
    audit("تعریف محدوده جغرافیایی", z["id"], z["name"])
    return z


@router.put("/api/v1/zones/{id}", response_model=Zone)
def edit_zone(id: str, p: ZoneInput):
    z = lookup("zones", id)
    z.update(p.model_dump())
    audit("ویرایش محدوده جغرافیایی", id)
    return z


@router.patch("/api/v1/assets/{id}/settings", response_model=Asset)
def asset_settings(id: str, p: AssetSettings):
    a = lookup("assets", id)
    changes = p.model_dump(exclude={"sms_password", "sms_login"}, exclude_none=True)
    a.update(changes)
    for key in ("sms_password", "sms_login"):
        if getattr(p, key) is not None:
            a[key] = getattr(p, key)
    a["sms_password_set"] = bool(a.get("sms_password"))
    audit("ویرایش مشخصات تجهیز", id, a.get("device_profile", "generic_data"))
    return legacy_asset(a)


@router.get("/api/v1/settings", response_model=RuntimeSettings)
def get_settings():
    return state["settings"]


def approved_gis_url(value):
    """HTTP(S) without credentials, on an origin the server operator approved (SEPEHR_GIS_ORIGINS).

    The same allowlist feeds the CSP connect-src, so an approved URL is also loadable by the browser.
    """
    try:
        url = urlsplit(value)
        valid = url.scheme in ("http", "https") and url.hostname and not url.username and not url.password
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(422, "آدرس سرویس GIS باید HTTP یا HTTPS و بدون اطلاعات ورود باشد")
    allowed = {origin.strip() for origin in os.environ.get("SEPEHR_GIS_ORIGINS", "").split(",") if origin.strip()}
    if f"{url.scheme}://{url.netloc}" not in allowed:
        raise HTTPException(422, "مبدأ GIS باید در فهرست سرویس‌های داخلی مصوب سرور باشد")
    return url


@router.put("/api/v1/settings", response_model=RuntimeSettings)
def save_settings(p: RuntimeSettings):
    if p.classification_label != state["settings"]["classification_label"]:
        raise HTTPException(409, "تغییر طبقه‌بندی فقط از صف تأیید دونفره مجاز است")
    if p.weak_coverage_timeout < p.normal_coverage_timeout:
        raise HTTPException(422, "آستانه پوشش ضعیف نباید از پوشش عادی کمتر باشد")
    if any(id not in {c["id"] for c in state["cameras"]} for id in p.intel_anpr_sensitive_camera_ids):
        raise HTTPException(422, "شناسه دوربین حساس باید در فهرست دوربین‌ها موجود باشد")
    if p.gis_mode != "local":
        approved_gis_url(p.gis_url)
        if not p.gis_layers.strip():
            raise HTTPException(422, "نام لایهٔ WMS یا نوع عارضهٔ WFS را وارد کنید")
        p.gis_layers = p.gis_layers.strip()
    if p.basemap_style_url:
        # The basemap style and everything it references must come from an approved internal origin.
        approved_gis_url(p.basemap_style_url)
    if any(state["settings"].get(key) != getattr(p, key) for key in ("intel_coverage_buffer_m", "intel_coverage_backfill_hours")):
        state["intel"].pop("coverage", None)
    from ..core import store
    from ..security import authz
    if p.station_sensitivity_labels != state["settings"]["station_sensitivity_labels"]:
        authz.require("admin")
    if p.patrol_game.model_dump() != state["settings"]["patrol_game"]:
        from ..intel.patrol_game import known_target, require_herasat
        require_herasat()
        if any(not known_target(o.target_id) for o in p.patrol_game.overrides):
            raise HTTPException(422, "شناسه هدف مقدار اختصاصی در لایه‌ها یا ایستگاه‌ها پیدا نشد")
    if any(s["sensitivity"] not in p.station_sensitivity_labels for s in store.field.records("stations")):
        raise HTTPException(409, "برچسب مورد استفاده ایستگاه را نمی‌توان حذف کرد")
    store.field.save("settings", dict(id="station_sensitivity", station_sensitivity_labels=p.station_sensitivity_labels))
    store.field.save('settings', dict(id='tour_phase_two', **{key: getattr(p, key).model_dump() if key in ('heat_profile', 'media_retention_days', 'report_routing', 'rate_limit_per_minute', 'patrol_game') else getattr(p, key)
        for key in ('tour_schedule_max_days', 'tour_time_jitter_percent', 'queue_reveal', 'queue_reveal_count',
                    'handover_required', 'two_person_window_minutes', 'heat_profile',
                    'field_location_max_accuracy_m', 'field_location_max_speed_kmh', 'field_clock_skew_seconds',
                    'field_man_down_idle_seconds', 'field_man_down_countdown_seconds', 'field_sos_escalation_seconds',
                    'offline_pbkdf2_iterations', 'offline_shift_grace_minutes', 'max_offline_minutes',
                    'media_chunk_bytes', 'media_single_upload_max_bytes', 'media_max_bytes', 'media_video_max_seconds',
                    'media_audio_max_seconds', 'media_video_bitrate_kbps', 'media_audio_bitrate_kbps',
                    'media_retention_days', 'report_routing', 'message_urgent_escalation_seconds',
                    'integrity_mode', 'integrity_window_hours', 'integrity_short_dwell_count',
                    'integrity_offline_repeat_count', 'integrity_pair_minutes', 'integrity_pair_km',
                    'exception_device_silence_minutes', 'rate_limit_per_minute', 'max_json_body_bytes', 'patrol_game')}))
    state["settings"] = p.model_dump()
    audit("ذخیره تنظیمات نمایشی", "SETTINGS")
    return p


@router.get("/api/v1/cameras", response_model=list[Camera])
def cameras():
    return state["cameras"]


@router.post("/api/v1/cameras/{id}/event", response_model=PlateReadResult, status_code=201)
def camera_event(id: str, p: CameraEventInput):
    from ..intel.ingest import plate_read, require_enabled

    require_enabled("intel_anpr_enabled")
    lookup("cameras", id)
    if p.event != "plate" or p.plate is None or p.time is None or p.vehicle_class is None:
        raise HTTPException(409, "رخداد ساختگی دوربین پردازش نمی‌شود؛ پلاک، زمان و رده واقعی خودرو لازم است")
    return plate_read(PlateReadInput(camera_id=id, plate=p.plate, time=p.time, vehicle_class=p.vehicle_class))
