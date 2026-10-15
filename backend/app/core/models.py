"""Public input and response contracts. Device adapters map into these domain records."""

from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

SEVERITY_LABELS = {"critical": "بحرانی", "high": "زیاد", "medium": "متوسط", "low": "کم", "info": "اطلاعاتی"}

def validate_coordinates(points):
    """Shared coordinate validation for zones and imported intelligence layers."""
    if any(len(p) != 2 or not (-180 <= p[0] <= 180 and -85 <= p[1] <= 85) for p in points):
        raise ValueError("هر نقطه باید طول و عرض جغرافیایی معتبر داشته باشد")
    return points


def validate_polygon(points):
    """The same polygon validity rules for zones and incident hazard areas."""
    validate_coordinates(points)
    if len(set(tuple(p) for p in points)) < 3:
        raise ValueError("حداقل سه نقطه متفاوت لازم است")
    area = sum(points[i][0] * points[(i + 1) % len(points)][1]
               - points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points)))
    if abs(area) < 1e-8:
        raise ValueError("مساحت چندضلعی باید مثبت باشد")
    return points


class EmergencyContact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=50)


class RiskWeights(BaseModel):
    model_config = ConfigDict(extra='forbid')
    incidents: float = Field(default=0.4, ge=0, le=10, allow_inf_nan=False)
    access: float = Field(default=0.2, ge=0, le=10, allow_inf_nan=False)
    staleness: float = Field(default=0.3, ge=0, le=10, allow_inf_nan=False)
    exposure: float = Field(default=0.1, ge=0, le=10, allow_inf_nan=False)

    @model_validator(mode="after")
    def positive_total(self):
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("حداقل یک وزن ریسک باید مثبت باشد")
        return self


def normalize_plate(value):
    """The same plate identity for reported reads and the operator's allowlist."""
    value = "".join(value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك", "01234567890123456789یک")).upper().split()).replace("-", "").replace("\u200c", "")
    if not value or len(value) > 32 or not value.isalnum():
        raise ValueError("پلاک باید شامل حروف و ارقام معتبر باشد")
    return value


class HeatProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    months: list[int] = Field(default_factory=list, max_length=12)
    restricted_hours: str = 'تمام شبانه‌روز'
    max_continuous_minutes: int = Field(default=240, ge=1, le=1440)
    checkin_minutes: int = Field(default=30, ge=1, le=1440)

    @field_validator('months')
    @classmethod
    def valid_months(cls, values):
        if any(v < 1 or v > 12 for v in values) or len(set(values)) != len(values):
            raise ValueError('ماه‌ها باید یکتا و بین ۱ تا ۱۲ باشند')
        return values

    @field_validator('restricted_hours')
    @classmethod
    def valid_hours(cls, value):
        from .engine import valid_schedule
        if not valid_schedule(value):
            raise ValueError('ساعات گرما باید بازه معتبر باشند')
        return value


class MediaRetention(BaseModel):
    model_config = ConfigDict(extra='forbid')
    security: int = Field(default=365, ge=1, le=3650)
    safety_hse: int = Field(default=365, ge=1, le=3650)
    operations: int = Field(default=180, ge=1, le=3650)
    damage: int = Field(default=730, ge=1, le=3650)
    uxo: int = Field(default=730, ge=1, le=3650)
    drone_sighting: int = Field(default=730, ge=1, le=3650)
    other: int = Field(default=90, ge=1, le=3650)


def _audiences(*values):
    return Field(default_factory=lambda: list(values), min_length=1, max_length=3)


class ReportRouting(BaseModel):
    model_config = ConfigDict(extra='forbid')
    security: list[Literal['security', 'hse', 'operations']] = _audiences('security')
    safety_hse: list[Literal['security', 'hse', 'operations']] = _audiences('security', 'hse', 'operations')
    operations: list[Literal['security', 'hse', 'operations']] = _audiences('security', 'operations')
    damage: list[Literal['security', 'hse', 'operations']] = _audiences('security')
    uxo: list[Literal['security', 'hse', 'operations']] = _audiences('security', 'hse')
    drone_sighting: list[Literal['security', 'hse', 'operations']] = _audiences('security')
    other: list[Literal['security', 'hse', 'operations']] = _audiences('security')

    @model_validator(mode='after')
    def security_always(self):
        for values in self.model_dump().values():
            if 'security' not in values or len(set(values)) != len(values):
                raise ValueError('حراست باید مخاطب هر دسته گزارش باشد و مخاطب تکراری مجاز نیست')
        return self


class RateLimits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enroll: int = Field(default=10, ge=1, le=10000)
    pin: int = Field(default=10, ge=1, le=10000)
    scan: int = Field(default=60, ge=1, le=10000)
    upload: int = Field(default=600, ge=1, le=100000)
    # Emergency reports beyond this rate are accepted and flagged, never rejected.
    emergency: int = Field(default=10, ge=1, le=10000)


class TargetClassParameters(BaseModel):
    """Organisation-defined consequence value and expert baseline rate for one class of target."""
    model_config = ConfigDict(extra='forbid')
    key: str = Field(pattern=r'^(facility_unmanned|facility_manned|pipeline_segment|station_default|station:.{1,80})$')
    label: str = Field(min_length=1, max_length=100)
    value: float = Field(gt=0, le=100, allow_inf_nan=False)
    prior_rate_per_year: float = Field(ge=0.001, le=1000, allow_inf_nan=False)


class TargetOverride(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_id: str = Field(min_length=1, max_length=200)
    value: float | None = Field(default=None, gt=0, le=100, allow_inf_nan=False)
    prior_rate_per_year: float | None = Field(default=None, ge=0.001, le=1000, allow_inf_nan=False)
    always_visit: bool = False
    note: str = Field(min_length=3, max_length=300)


class EventWeights(BaseModel):
    """Evidence weight of each recorded event category in the Bayesian update."""
    model_config = ConfigDict(extra='forbid')
    incident: float = Field(default=1.0, ge=0, le=10)
    import_theft: float = Field(default=1.0, ge=0, le=10)
    import_sabotage: float = Field(default=1.0, ge=0, le=10)
    import_intrusion: float = Field(default=0.8, ge=0, le=10)
    import_tampering: float = Field(default=0.8, ge=0, le=10)
    import_vandalism: float = Field(default=0.6, ge=0, le=10)
    import_other: float = Field(default=0.4, ge=0, le=10)
    report_security: float = Field(default=1.0, ge=0, le=10)
    report_damage: float = Field(default=1.0, ge=0, le=10)
    report_uxo: float = Field(default=0.5, ge=0, le=10)
    report_drone_sighting: float = Field(default=0.5, ge=0, le=10)
    report_operations: float = Field(default=0.2, ge=0, le=10)
    report_safety_hse: float = Field(default=0.1, ge=0, le=10)
    report_other: float = Field(default=0.3, ge=0, le=10)
    seal_anomaly: float = Field(default=0.8, ge=0, le=10)
    tag_replay: float = Field(default=0.6, ge=0, le=10)


def _default_classes():
    rows = [('facility_unmanned', 'تأسیسات بدون سرنشین', 8, 2.0), ('facility_manned', 'تأسیسات دارای سرنشین', 6, 0.5),
            ('pipeline_segment', 'قطعه خط لوله', 5, 0.3), ('station_default', 'ایستگاه (پیش‌فرض)', 5, 0.5),
            ('station:حیاتی', 'ایستگاه حیاتی', 10, 1.5), ('station:حساس', 'ایستگاه حساس', 7, 1.0),
            ('station:مهم', 'ایستگاه مهم', 5, 0.5), ('station:قابل حفاظت', 'ایستگاه قابل حفاظت', 3, 0.25)]
    return [TargetClassParameters(key=k, label=l, value=v, prior_rate_per_year=r) for k, l, v, r in rows]


class PatrolGameSettings(BaseModel):
    """Every organisation-specific input of the patrol security game; edited in the UI, approved by Herasat."""
    model_config = ConfigDict(extra='forbid')
    model: Literal['stackelberg', 'quantal', 'weighted'] = 'stackelberg'
    threat_profile: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    quantal_rationality: float = Field(default=4.0, ge=0, le=50, allow_inf_nan=False)
    attack_minutes: float = Field(default=90, ge=1, le=1440, allow_inf_nan=False)
    max_detection: float = Field(default=0.9, gt=0, le=1, allow_inf_nan=False)
    capture_penalty: float = Field(default=0.5, ge=0, le=10, allow_inf_nan=False)
    risk_quantile: float = Field(default=0.5, ge=0.5, le=0.99, allow_inf_nan=False)
    credible_level: float = Field(default=0.9, ge=0.5, le=0.99, allow_inf_nan=False)
    prior_strength_years: float = Field(default=1.0, ge=0.1, le=20, allow_inf_nan=False)
    half_life_days: float = Field(default=365, ge=7, le=3650, allow_inf_nan=False)
    spatial_bandwidth_m: float = Field(default=300, ge=10, le=10000, allow_inf_nan=False)
    history_start: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    allow_subset_tours: bool = False
    classes: list[TargetClassParameters] = Field(default_factory=_default_classes, min_length=4, max_length=200)
    overrides: list[TargetOverride] = Field(default_factory=list, max_length=2000)
    event_weights: EventWeights = Field(default_factory=EventWeights)

    @model_validator(mode='after')
    def consistent(self):
        keys = [c.key for c in self.classes]
        if len(set(keys)) != len(keys):
            raise ValueError('کلید هر دسته هدف باید یکتا باشد')
        missing = {'facility_unmanned', 'facility_manned', 'pipeline_segment', 'station_default'} - set(keys)
        if missing:
            raise ValueError('دسته‌های پایه هدف الزامی‌اند: ' + '، '.join(sorted(missing)))
        targets = [o.target_id for o in self.overrides]
        if len(set(targets)) != len(targets):
            raise ValueError('برای هر هدف فقط یک مقدار اختصاصی مجاز است')
        if any(o.value is None and o.prior_rate_per_year is None and not o.always_visit for o in self.overrides):
            raise ValueError('مقدار اختصاصی باید ارزش، نرخ پایه یا بازدید الزامی را تعیین کند')
        if self.history_start:
            datetime.fromisoformat(self.history_start)
        return self


class RuntimeSettings(BaseModel):
    patrol_game: PatrolGameSettings = Field(default_factory=PatrolGameSettings)
    rate_limit_per_minute: RateLimits = Field(default_factory=RateLimits)
    max_json_body_bytes: int = Field(default=2097152, ge=65536, le=16777216)
    # Live trail length sent with the operational picture; full history comes from the track API.
    map_trail_points: int = Field(default=60, ge=0, le=500)
    # Evidence needed before a communication-gap cell raises a (shadow) finding.
    intel_comm_gap_min_events: int = Field(default=3, ge=1, le=1000)
    model_config = ConfigDict(extra='forbid')
    integrity_mode: Literal['shadow', 'active'] = 'shadow'
    integrity_window_hours: float = Field(default=24, gt=0, le=720, allow_inf_nan=False)
    integrity_short_dwell_count: int = Field(default=3, ge=2, le=100)
    integrity_offline_repeat_count: int = Field(default=3, ge=2, le=100)
    integrity_pair_minutes: float = Field(default=10, gt=0, le=240, allow_inf_nan=False)
    integrity_pair_km: float = Field(default=1, gt=0, le=100, allow_inf_nan=False)
    exception_device_silence_minutes: int = Field(default=10, ge=1, le=1440)
    media_chunk_bytes: int = Field(default=262144, ge=16384, le=4194304)
    media_single_upload_max_bytes: int = Field(default=1048576, ge=1024, le=8388608)
    media_max_bytes: int = Field(default=104857600, ge=65536, le=1073741824)
    media_video_max_seconds: int = Field(default=60, ge=5, le=1800)
    media_audio_max_seconds: int = Field(default=180, ge=5, le=3600)
    media_video_bitrate_kbps: int = Field(default=1000, ge=64, le=8000)
    media_audio_bitrate_kbps: int = Field(default=64, ge=16, le=320)
    media_retention_days: MediaRetention = Field(default_factory=MediaRetention)
    report_routing: ReportRouting = Field(default_factory=ReportRouting)
    message_urgent_escalation_seconds: int = Field(default=120, ge=10, le=3600)
    field_location_max_accuracy_m: float = Field(default=100, gt=0, le=1000)
    field_location_max_speed_kmh: float = Field(default=180, gt=0, le=500)
    field_clock_skew_seconds: int = Field(default=120, ge=1, le=3600)
    field_man_down_idle_seconds: int = Field(default=120, ge=10, le=3600)
    field_man_down_countdown_seconds: int = Field(default=30, ge=5, le=300)
    field_sos_escalation_seconds: int = Field(default=60, ge=10, le=3600)
    offline_pbkdf2_iterations: int = Field(default=310000, ge=100000, le=2000000)
    offline_shift_grace_minutes: int = Field(default=60, ge=0, le=1440)
    max_offline_minutes: int = Field(default=120, ge=1, le=10080)
    tour_schedule_max_days: int = Field(default=31, ge=1, le=366)
    tour_time_jitter_percent: int = Field(default=15, ge=0, le=50)
    queue_reveal: Literal['all', 'next_n'] = 'next_n'
    queue_reveal_count: int = Field(default=1, ge=1, le=50)
    handover_required: bool = False
    two_person_window_minutes: int = Field(default=15, ge=1, le=120)
    heat_profile: 'HeatProfile' = Field(default_factory=lambda: HeatProfile())
    station_sensitivity_labels: list[str] = Field(default_factory=lambda: ["حیاتی", "حساس", "مهم", "قابل حفاظت"], min_length=1, max_length=50)

    @field_validator("station_sensitivity_labels")
    @classmethod
    def sensitivity_labels(cls, labels):
        if len(set(labels)) != len(labels) or any(not v.strip() or len(v) > 80 for v in labels):
            raise ValueError("برچسب‌های حساسیت باید یکتا و غیرخالی باشند")
        return labels

    classification_label: str = Field(default="محرمانه", min_length=1, max_length=80)
    organization: str = Field(default="نفت و گاز آغاجاری", min_length=3, max_length=100)
    retention_days: int = Field(default=90, ge=7, le=3650)
    weak_coverage_timeout: int = Field(default=20, ge=1, le=120)
    normal_coverage_timeout: int = Field(default=5, ge=1, le=120)
    dedupe_seconds: int = Field(default=60, ge=5, le=3600)
    intel_tick_seconds: int = Field(default=5, ge=1, le=3600)
    intel_coverage_buffer_m: float = Field(default=200, ge=0, le=10000, allow_inf_nan=False)
    intel_coverage_backfill_hours: float = Field(default=72, gt=0, le=8760, allow_inf_nan=False)
    intel_coverage_stale_hours: float = Field(default=12, gt=0, le=8760, allow_inf_nan=False)
    intel_coverage_unmanned_stale_hours: float = Field(default=8, gt=0, le=8760, allow_inf_nan=False)
    intel_coverage_mode: Literal["shadow", "active"] = "shadow"
    intel_safety_stop_minutes: float = Field(default=3, gt=0, le=120, allow_inf_nan=False)
    intel_safety_checkin_minutes: float = Field(default=10, gt=0, le=120, allow_inf_nan=False)
    intel_safety_remote_km: float = Field(default=1, ge=0, le=100, allow_inf_nan=False)
    intel_safety_normal_hours: str = "06:00–20:00"
    intel_safety_mode: Literal["shadow", "active"] = "shadow"
    intel_hazard_approach_km: float = Field(default=2, ge=0, le=100, allow_inf_nan=False)
    intel_risk_weights: RiskWeights = Field(default_factory=RiskWeights)
    intel_risk_incident_radius_m: float = Field(default=500, gt=0, le=100000, allow_inf_nan=False)
    intel_risk_half_life_days: float = Field(default=30, gt=0, le=3650, allow_inf_nan=False)
    intel_risk_alpha: float = Field(default=2, gt=0, le=10, allow_inf_nan=False)
    intel_plan_dwell_minutes: float = Field(default=10, ge=0, le=240, allow_inf_nan=False)
    intel_plan_time_jitter_minutes: float = Field(default=60, ge=0, le=720, allow_inf_nan=False)
    intel_plan_window_minutes: float = Field(default=30, ge=0, le=240, allow_inf_nan=False)
    intel_shifts: list[str] = Field(default_factory=lambda: ["06:00–14:00", "14:00–22:00", "22:00–06:00"], min_length=1, max_length=24)
    intel_pressure_enabled: bool = False
    intel_pressure_mode: Literal["shadow", "active"] = "shadow"
    intel_anpr_enabled: bool = False
    intel_vehicle_allowlist: list[str] = Field(default_factory=list, max_length=10000)
    intel_anpr_night_hours: str = "22:00–06:00"
    intel_anpr_repeat_window_minutes: float = Field(default=30, gt=0, le=1440, allow_inf_nan=False)
    intel_anpr_sensitive_camera_ids: list[str] = Field(default_factory=list, max_length=1000)
    intel_emergency_contacts: list[EmergencyContact] = Field(default_factory=list, max_length=20)
    shadow_mode: bool = True
    maintenance_silence: bool = False
    gis_mode: Literal["local", "wms", "wfs"] = "local"
    gis_url: str = Field(default="", max_length=500)
    gis_layers: str = Field(default="", max_length=500)
    gis_wms_version: Literal["1.1.1", "1.3.0"] = "1.3.0"
    gis_wfs_version: Literal["1.1.0", "2.0.0"] = "2.0.0"
    gis_opacity: float = Field(default=0.7, ge=0, le=1)
    # Internal MapLibre style (tiles, glyphs, sprites on approved origins). Empty: schematic map,
    # no basemap and no network request; public tile services are never used in production.
    basemap_style_url: str = Field(default="", max_length=500)

    @field_validator("intel_safety_normal_hours", "intel_anpr_night_hours")
    @classmethod
    def valid_normal_hours(cls, value):
        from .engine import valid_schedule

        value = value.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        if not valid_schedule(value):
            raise ValueError("بازه ساعت باید مانند 06:00–20:00 یا تمام شبانه‌روز باشد")
        return value

    @field_validator("intel_shifts")
    @classmethod
    def valid_shifts(cls, values):
        from .engine import valid_schedule

        values = [v.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).replace("-", "–") for v in values]
        if any(not valid_schedule(v) for v in values) or len(set(values)) != len(values):
            raise ValueError("شیفت‌ها باید بازه‌های معتبر و غیرتکراری مانند 06:00–14:00 باشند")
        return values

    @field_validator("intel_vehicle_allowlist")
    @classmethod
    def valid_allowlist(cls, values):
        return list(dict.fromkeys(normalize_plate(value) for value in values))

    @field_validator("intel_anpr_sensitive_camera_ids")
    @classmethod
    def valid_sensitive_cameras(cls, values):
        values = [v.strip() for v in values]
        if any(not v or len(v) > 100 for v in values) or len(set(values)) != len(values):
            raise ValueError("شناسه دوربین حساس باید معتبر و غیرتکراری باشد")
        return values


class AccessAttributes(BaseModel):
    road_distance_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    village_distance_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    heavy_vehicle_access: bool | None = None


class Pipeline(AccessAttributes):
    id: str
    name: str
    field: str
    points: list[list[float]]


class Facility(AccessAttributes):
    id: str
    name: str
    kind: Literal["well", "station", "plant", "manifold"]
    lon: float
    lat: float
    radius_m: float
    unmanned: bool
    field: str


class Segment(AccessAttributes):
    id: str
    pipeline_id: str
    index: int
    points: list[list[float]]
    length_m: float
    field: str


class LineGeometry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal["LineString"]
    coordinates: list[list[float]] = Field(min_length=2, max_length=10000)

    @field_validator("coordinates")
    @classmethod
    def valid_line(cls, points):
        validate_coordinates(points)
        if len(set(tuple(p) for p in points)) < 2:
            raise ValueError("خط باید حداقل دو نقطه متفاوت داشته باشد")
        return points


class PointGeometry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal["Point"]
    coordinates: list[float]

    @field_validator("coordinates")
    @classmethod
    def valid_point(cls, point):
        validate_coordinates([point])
        return point


class LayerProperties(AccessAttributes):
    model_config = ConfigDict(extra='forbid')
    id: str | None = Field(default=None, min_length=1, max_length=100)
    name: str = Field(min_length=3, max_length=100)
    field: str = Field(min_length=1, max_length=100)


class FacilityProperties(LayerProperties):
    model_config = ConfigDict(extra='forbid')
    kind: Literal["well", "station", "plant", "manifold"]
    radius_m: float = Field(gt=0, allow_inf_nan=False)
    unmanned: bool


class LineFeature(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal["Feature"]
    geometry: LineGeometry
    properties: LayerProperties


class PointFeature(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal["Feature"]
    geometry: PointGeometry
    properties: FacilityProperties


class LayerImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal["FeatureCollection"]
    features: list[LineFeature | PointFeature] = Field(min_length=1, max_length=1000)


class LayerImportResult(BaseModel):
    pipelines: list[Pipeline]
    facilities: list[Facility]
    segments: list[Segment]


class FindingEvidence(BaseModel):
    rule: str = Field(min_length=1)
    thresholds: dict[str, Any]
    window_from: AwareDatetime
    window_to: AwareDatetime
    points: list[tuple[float, float, AwareDatetime]]
    values: dict[str, Any]

    @field_validator("points")
    @classmethod
    def valid_points(cls, points):
        validate_coordinates([list(p[:2]) for p in points])
        return points


class Finding(BaseModel):
    id: str
    kind: str
    rule_id: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    mode: Literal["shadow", "active"] = "shadow"
    status: Literal["open", "acknowledged", "resolved"] = "open"
    created_at: str
    updated_at: str
    subject_ids: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: FindingEvidence
    sources: list[str]
    incident_id: str | None = None
    can_execute: Literal[False] = False


class CoverageItem(BaseModel):
    id: str
    kind: Literal["segment", "facility"]
    status: Literal["ok", "stale", "never"]
    last_visit: str | None = None
    last_asset_id: str | None = None
    age_minutes: float | None = None


class CoverageTotals(BaseModel):
    percent_ok: float
    by_field: dict[str, float]


class Coverage(BaseModel):
    items: list[CoverageItem]
    totals: CoverageTotals


class SafetyEpisode(BaseModel):
    asset_id: str
    state: Literal["idle", "stopped", "check_pending", "confirmed", "escalated"]
    started_at: str | None = None
    deadline: str | None = None
    facility_id: str | None = None
    reason: str


class SafetyStatus(BaseModel):
    episodes: list[SafetyEpisode]


class SafetyConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str | None = Field(default=None, max_length=1000)


class DeviceEventInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal["sos"]
    time: AwareDatetime


class DeviceEvent(BaseModel):
    id: str
    asset_id: str
    type: Literal["sos"]
    time: str
    received_at: str
    alert_ids: list[str]
    incident_ids: list[str]


class TrackPoint(BaseModel):
    lon: float
    lat: float
    time: str


PositionFlag = Literal["accuracy_unknown", "low_accuracy", "clock_ahead", "late", "implausible_speed"]


class PositionReceipt(TrackPoint):
    """What the server did with one observation: durable first, then accepted for live or history only."""
    received_at: str
    created: bool
    live: bool
    flags: list[PositionFlag] = Field(default_factory=list)


class PositionObservation(BaseModel):
    """Raw stored observation with its quality evidence; live=false points never moved the live position."""
    lon: float
    lat: float
    time: str
    speed: float | None
    source: Literal["reported", "demo"]
    received_at: str | None
    accuracy_m: float | None
    fix_source: str
    sequence: int | None
    auth: str | None
    flags: list[str]
    live: bool


class Asset(BaseModel):
    keycloak_sub: str | None = None
    zone_id: str | None = None
    contractor_id: str | None = None
    id: str
    name: str
    kind: Literal["vehicle", "person"]
    status: Literal["online", "offline", "warning"]
    lon: float
    lat: float
    speed: float
    battery: int
    signal: int
    field: str
    mission: str
    operator: str
    sim: str
    carrier: str
    firmware: str
    last_seen: str
    report_interval: int = 30
    data_package: str = "active"
    unit: Literal["patrol", "field", "org"] = "patrol"
    authorized: bool = True
    capabilities: list[str]
    track: list[TrackPoint]
    patrol_base: list[float] | None = None
    device_profile: str = "generic_data"
    sms_password_set: bool = False
    # fresh: inside the observation gap; no_fix: the device is talking but sends no position;
    # stale: nothing recent and silence alone cannot tell power-off from lost coverage.
    position_state: Literal["fresh", "stale", "no_fix", "unknown", "simulated"] = "unknown"
    position_age_seconds: float | None = None
    position_accuracy_m: float | None = None
    position_flags: list[str] = Field(default_factory=list)
    last_contact_at: str | None = None

    @field_validator("patrol_base")
    @classmethod
    def valid_base(cls, point):
        if point is not None:
            validate_coordinates([point])
        return point


class TimelineEntry(BaseModel):
    time: str
    action: str
    actor: str


class HazardAccess(BaseModel):
    access_points: list[list[float]] = Field(default_factory=list, max_length=100)

    @field_validator("access_points")
    @classmethod
    def valid_access(cls, points):
        return validate_coordinates(points)


class HazardCircle(HazardAccess):
    model_config = ConfigDict(extra='forbid')
    type: Literal["circle"]
    center: list[float]
    radius_m: float = Field(gt=0, le=100000, allow_inf_nan=False)

    @field_validator("center")
    @classmethod
    def valid_center(cls, point):
        validate_coordinates([point])
        return point


class HazardPolygon(HazardAccess):
    model_config = ConfigDict(extra='forbid')
    type: Literal["polygon"]
    points: list[list[float]] = Field(min_length=3, max_length=100)

    @field_validator("points")
    @classmethod
    def valid_points(cls, points):
        return validate_polygon(points)


HazardArea = Annotated[HazardCircle | HazardPolygon, Field(discriminator="type")]


class IncidentCreation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=3, max_length=200)
    severity: Literal["critical", "high", "medium", "low", "info"]
    lon: float
    lat: float
    description: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def valid_location(self):
        validate_coordinates([[self.lon, self.lat]])
        return self


class Incident(BaseModel):
    id: str
    title: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    status: Literal[
        "detected", "confirmed", "assigned", "en_route", "on_scene", "closed"
    ]
    zone: str
    asset_id: str
    lon: float
    lat: float
    created_at: str
    assigned_to: str | None = None
    zone_id: str | None = None
    policy_id: str | None = None
    eta_minutes: float | None = None
    arrived_at: str | None = None
    operator_ack_at: str | None = None
    description: str
    timeline: list[TimelineEntry]
    kind: Literal["patrol_safety", "sos", "process", "pressure_drop", "anpr"] | None = None
    pressure_context: "PressureContext | None" = None
    hazard_area: HazardArea | None = None
    emergency_contacts: list[EmergencyContact] = Field(default_factory=list)
    backup_patrols: list["NearbyPatrol"] = Field(default_factory=list)
    route: "RoadRoute | None" = None
    route_alternatives: list["RoadRoute"] = Field(default_factory=list)


class NearbyPatrol(BaseModel):
    asset_id: str
    name: str
    distance_km: float
    distance_type: Literal["straight_line", "road"]
    eta_minutes: float
    lon: float
    lat: float
    position_state: str = "unknown"
    position_age_seconds: float | None = None
    needs_confirmation: bool = False


class DispatchExclusion(BaseModel):
    asset_id: str
    name: str
    reason: str


class DispatchOptions(BaseModel):
    """Explainable dispatch suggestion; the operator confirms before any assignment."""
    suggestions: list[NearbyPatrol]
    needs_confirmation: list[NearbyPatrol]
    excluded: list[DispatchExclusion]
    eta_basis: str
    computed_at: str


class CommGapCell(BaseModel):
    id: str
    lon: float
    lat: float
    cell_m: float
    samples: int
    offline_samples: int
    silences: int
    silence_minutes: float
    assets: int
    confidence: Literal["low", "medium"]
    finding_id: str | None = None


class CommGapLayer(BaseModel):
    cells: list[CommGapCell]
    window_from: str
    window_to: str
    method: str


class PressureContext(BaseModel):
    event_id: str
    pipeline_id: str
    segment_id: str
    last_visit: CoverageItem
    nearest_patrol: NearbyPatrol | None = None
    nearest_patrol_position_source: str | None = None


class PipelinePressureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pipeline_id: str = Field(min_length=1, max_length=100)
    chainage_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    segment_id: str | None = Field(default=None, min_length=1, max_length=100)
    time: AwareDatetime
    pressure_drop_pct: float = Field(gt=0, le=100, allow_inf_nan=False)
    source: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_location(self):
        if (self.chainage_m is None) == (self.segment_id is None):
            raise ValueError("دقیقاً یکی از chainage_m یا segment_id لازم است")
        self.source = self.source.strip()
        if not self.source or self.source.casefold() in {"demo", "sample", "synthetic", "simulated", "نمونه", "نمایشی", "ساختگی"}:
            raise ValueError("منبع واقعی اندازه‌گیری لازم است؛ منبع ساختگی پذیرفته نمی‌شود")
        return self


class PipelinePressureEvent(BaseModel):
    id: str
    pipeline_id: str
    segment_id: str
    chainage_m: float | None = None
    time: str
    received_at: str
    pressure_drop_pct: float
    source: str
    lon: float
    lat: float
    finding_id: str


class PipelinePressureResult(BaseModel):
    event: PipelinePressureEvent
    finding: Finding
    incident: Incident | None = None


class PlateReadFields(BaseModel):
    plate: str = Field(min_length=1, max_length=64)
    time: AwareDatetime
    vehicle_class: Literal["heavy", "light", "unknown"]

    @field_validator("plate")
    @classmethod
    def valid_plate(cls, value):
        return normalize_plate(value)


class PlateReadInput(PlateReadFields):
    model_config = ConfigDict(extra="forbid")
    camera_id: str = Field(min_length=1, max_length=100)


class CameraEventInput(BaseModel):
    """Legacy adapter requires real plate fields; old demo-only payloads are rejected."""
    model_config = ConfigDict(extra="forbid")
    event: Literal["intrusion", "fire", "plate"] = "plate"
    plate: str | None = Field(default=None, min_length=1, max_length=64)
    time: AwareDatetime | None = None
    vehicle_class: Literal["heavy", "light", "unknown"] | None = None

    @field_validator("plate")
    @classmethod
    def valid_plate(cls, value):
        return normalize_plate(value) if value is not None else None


class PlateReadEvent(BaseModel):
    id: str
    type: Literal["plate_read"] = "plate_read"
    source: Literal["reported"] = "reported"
    camera_id: str
    plate: str
    time: str
    received_at: str
    vehicle_class: Literal["heavy", "light", "unknown"]
    lon: float
    lat: float
    sensitive: bool
    alert_ids: list[str]
    finding_ids: list[str]
    incident_ids: list[str]


class PlateReadResult(BaseModel):
    event: PlateReadEvent
    alerts: list["Alert"]
    findings: list[Finding]
    incidents: list[Incident]


class HazardAsset(BaseModel):
    asset_id: str
    name: str
    distance_to_boundary_km: float
    finding_id: str | None = None


class ClosureSuggestion(NearbyPatrol):
    eta_label: Literal["تخمینی"] = "تخمینی"
    target: list[float]
    access_point_index: int | None = None


class HazardStatus(BaseModel):
    inside: list[HazardAsset]
    approaching: list[HazardAsset]
    closure_suggestions: list[ClosureSuggestion]


class IncidentReport(BaseModel):
    incident: Incident
    hazard: HazardStatus
    generated_at: str
    mock: bool


class DeviceEventResult(BaseModel):
    event: DeviceEvent
    alerts: list["Alert"]
    incidents: list[Incident]


class Command(BaseModel):
    id: str
    asset_id: str
    command: Literal["position", "ping", "interval", "restart", "beacon", "diagnostics"]
    channel: Literal["data", "sms"]
    interval_seconds: int
    request_id: str
    status: Literal["sent", "delivered", "executed", "timed_out"]
    created_at: str
    updated_at: str
    epoch: float
    timeout_seconds: int
    actor: str
    mock: bool
    device_profile: str = "generic_data"
    sms_destination: str | None = None
    sms_text: str | None = None
    gateway: Literal["none"] = "none"


class PolicyTestResult(BaseModel):
    matches: int
    false_positives: int | None
    samples: int
    assumptions: str
    period: str
    mock: bool


class AuditVerification(BaseModel):
    valid: bool
    count: int
    scope: str | None = None


class Policy(BaseModel):
    id: str
    name: str
    zone: str
    subject: str
    condition: str
    threshold: int
    schedule: str
    action: str
    severity: str
    status: Literal["draft", "tested", "shadow", "active"]
    version: int
    matches: int
    false_positives: int
    approver: str | None = None
    test_result: PolicyTestResult | None = None


class Zone(BaseModel):
    id: str
    name: str
    risk: str
    coverage: Literal["normal", "weak"] = "normal"
    points: list[list[float]]


class AuditRecord(BaseModel):
    sub: str | None = None
    username: str | None = None
    prev_hash: str
    id: str
    time: str
    actor: str
    action: str
    target: str
    detail: str
    previous_hash: str
    hash: str


class Checkpoint(BaseModel):
    name: str
    visited: bool
    target_id: str | None = None
    lon: float | None = None
    lat: float | None = None
    due_at: str | None = None
    visited_at: str | None = None


class Mission(BaseModel):
    id: str
    name: str
    asset_id: str
    zone: str
    status: str
    progress: int
    checkpoints: list[Checkpoint]
    plan_id: str | None = None
    plan_window_minutes: float | None = None


class RiskFactor(BaseModel):
    factor: Literal["incidents", "access", "staleness", "exposure"]
    raw: Any
    normalized: float
    weight: float
    contribution: float


class BayesEstimate(BaseModel):
    prior_rate: float
    prior_years: float
    weighted_events: float
    exposure_years: float
    shape: float
    rate: float
    mean: float
    lower: float
    upper: float
    planning_rate: float
    credible: float
    quantile: float
    event_ids: list[str] = Field(default_factory=list)


class RiskItem(BaseModel):
    id: str
    kind: Literal["segment", "facility"]
    name: str
    field: str
    lon: float
    lat: float
    score: float
    breakdown: list[RiskFactor]
    finding_id: str
    target_class: str = ''
    value: float = 0
    bayes: BayesEstimate | None = None


class RiskStatus(BaseModel):
    items: list[RiskItem]
    max_score: float
    computed_at: str


class PatrolPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shift_start: AwareDatetime
    shift_end: AwareDatetime
    asset_ids: list[str] = Field(min_length=1, max_length=50)
    stops_per_patrol: int = Field(default=3, ge=1, le=50)

    @model_validator(mode="after")
    def valid_shift(self):
        if self.shift_end <= self.shift_start or (self.shift_end - self.shift_start).total_seconds() > 7 * 86400:
            raise ValueError("پایان شیفت باید پس از آغاز و طول شیفت حداکثر هفت روز باشد")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("شناسه گشت‌ها نباید تکراری باشد")
        return self


class PatrolPlanStop(BaseModel):
    target_id: str
    kind: Literal["segment", "facility"]
    name: str
    field: str
    lon: float
    lat: float
    due_at: str
    score: float
    breakdown: list[RiskFactor]
    finding_id: str
    mandatory: bool


class PlannedPatrol(BaseModel):
    asset_id: str
    base: list[float]
    stops: list[PatrolPlanStop]


class PatrolPlan(BaseModel):
    id: str
    status: Literal["draft", "approved", "discarded"]
    shift_start: str
    shift_end: str
    created_at: str
    approved_at: str | None = None
    discarded_at: str | None = None
    patrols: list[PlannedPatrol]
    settings_snapshot: dict[str, Any]
    mission_ids: list[str]
    warnings: list[str]
    finding_id: str
    strategy: 'PatrolStrategy | None' = None
    can_execute: Literal[False] = False


class FieldMetric(BaseModel):
    name: str
    events: int
    coverage: float


class Alert(BaseModel):
    id: str
    time: str
    policy_id: str
    policy: str
    asset_id: str
    zone: str
    severity: str
    mode: Literal["shadow", "active"]
    routed: bool
    reason: str
    clock: str
    incident_id: str | None = None
    mission_id: str | None = None
    target_id: str | None = None
    checkpoint_index: int | None = None
    due_at: str | None = None
    event_id: str | None = None
    camera_id: str | None = None
    plate: str | None = None
    finding_id: str | None = None


class Summary(BaseModel):
    online: int
    total: int
    offline: int = 0
    warning: int = 0
    maintenance: int = 0
    critical: int
    open_incidents: int
    closed_incidents: int = 0
    missions: int
    policy_alerts: int = 0
    shadow_alerts: int = 0
    active_policies: int = 0
    hot_zone: str = ""
    coverage: float
    response_minutes: float
    availability: float
    trend: list[int]
    cycle: list[float]
    cycle_measured: list[bool] = []
    cycle_samples: list[int] = []
    fields: list[FieldMetric]
    mock: bool


class Bootstrap(BaseModel):
    assets: list[Asset]
    incidents: list[Incident]
    zones: list[Zone]
    policies: list[Policy]
    missions: list[Mission]
    commands: list[Command]
    audit: list[AuditRecord]
    alerts: list[Alert] = []
    pipelines: list[Pipeline]
    facilities: list[Facility]
    summary: Summary
    meta: dict[str, str]


class ChangeSet(BaseModel):
    """Entities changed after a cursor. reset=true: reload the snapshot (restart, gap or unknown cursor)."""
    cursor: str
    reset: bool
    assets: list[Asset] = Field(default_factory=list)
    incidents: list[Incident] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    missions: list[Mission] = Field(default_factory=list)
    commands: list[Command] = Field(default_factory=list)
    removed: dict[str, list[str]] = Field(default_factory=dict)
    summary: Summary | None = None
    server_time: str


class MapFeature(BaseModel):
    id: str
    layer: Literal["assets", "incidents", "facilities"]
    name: str
    lon: float
    lat: float
    status: str
    kind: str | None = None
    position_state: str | None = None
    severity: str | None = None


class MapFeatureResult(BaseModel):
    features: list[MapFeature]
    total: int
    truncated: bool


class TrackBatch(BaseModel):
    tracks: dict[str, list[TrackPoint]]
    truncated: bool


class ShiftReportLine(BaseModel):
    text: str
    source_ids: list[str] = Field(min_length=1)


class ShiftReportSection(BaseModel):
    title: str
    partial: bool
    notes: list[str]
    counts: dict[str, int | float | None]
    lines: list[ShiftReportLine]


class ShiftReport(BaseModel):
    window_from: str
    window_to: str
    timezone: Literal["Asia/Tehran"] = "Asia/Tehran"
    generated_at: str
    data_since: str
    data_source_id: str
    partial: bool
    headlines: list[ShiftReportLine]
    sections: dict[Literal["incidents", "coverage", "trackers", "commands", "compliance", "safety", "findings"], ShiftReportSection]
    can_execute: Literal[False] = False


class AssistantAnswer(BaseModel):
    answer: str
    sources: list[str]
    mock: bool
    can_execute: bool


class ZoneInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=3, max_length=100)
    risk: Literal["high", "medium", "low"] = "medium"
    coverage: Literal["normal", "weak"] = "normal"
    points: list[list[float]] = Field(min_length=3, max_length=100)

    @field_validator("points")
    @classmethod
    def valid_polygon(cls, points):
        return validate_polygon(points)


class AssetSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    carrier: Literal["همراه اول", "ایرانسل", "رایتل"]
    sim: str = Field(min_length=4, max_length=30)
    report_interval: int = Field(ge=5, le=3600)
    data_package: Literal["active", "expiring", "expired"] = "active"
    device_profile: Literal["generic_data", "concox_gt06", "coban_tk103", "teltonika_fmb"] | None = None
    # Write-only device SMS credentials; never returned and never stored in command records.
    sms_password: str | None = Field(default=None, max_length=32, pattern=r"^[0-9A-Za-z]*$")
    sms_login: str | None = Field(default=None, max_length=32, pattern=r"^[0-9A-Za-z]*$")


class DeviceProfile(BaseModel):
    id: str
    label: str
    family: str
    sms_commands: list[str]
    note: str


class CommandPreview(BaseModel):
    asset_id: str
    device_profile: str
    channel: Literal["data", "sms"]
    sms_destination: str | None
    sms_text: str | None
    gateway: Literal["none"] = "none"
    note: str


class Camera(BaseModel):
    id: str
    name: str
    zone: str
    lon: float
    lat: float
    status: Literal["online", "offline"]
    analysis: str



class Transition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal["confirmed", "assigned", "en_route", "on_scene", "closed"]
    asset_id: str | None = None
    route_id: str | None = Field(default=None, pattern=r"^R[1-3]$")
    note: str = Field(default="", max_length=1000)



class PolicyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=3, max_length=120)
    zone: str
    subject: Literal["vehicle", "person", "all"] = "vehicle"
    condition: Literal[
        "geofence_entry",
        "unknown_vehicle",
        "route_deviation",
        "after_hours",
        "long_stop",
        "connection_lost",
        "tamper",
        "gps_jump",
        "sos",
        "missed_checkpoint",
        "correlated_events",
        "camera_event",
    ] = "geofence_entry"
    threshold: int = Field(default=1, ge=1, le=3600)
    schedule: str = Field(default="تمام شبانه‌روز", max_length=100)
    action: Literal["create_incident", "notify", "suggest_patrol", "log_only"] = (
        "create_incident"
    )
    severity: Literal["critical", "high", "medium", "low", "info"] = "high"

    @field_validator("schedule")
    @classmethod
    def schedule_format(cls, value):
        value = value.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        from .engine import valid_schedule

        if not valid_schedule(value):
            raise ValueError("بازه زمانی باید مانند 22:00–06:00 یا تمام شبانه‌روز باشد")
        return value


class PolicyStatus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal["shadow", "active", "draft"]



class CommandInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    asset_id: str
    command: Literal["position", "ping", "interval", "restart", "beacon", "diagnostics"]
    channel: Literal["data", "sms"] = "data"
    interval_seconds: int = Field(default=30, ge=5, le=3600)
    request_id: str = Field(min_length=1, max_length=100)



class PositionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    lat: float = Field(ge=-85.051129, le=85.051129, allow_inf_nan=False)
    time: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    speed: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    # Unknown accuracy stays null; it is never treated as 0 m.
    accuracy_m: float | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    fix_source: Literal["gnss", "network", "fused", "manual", "unknown"] = "unknown"
    sequence: int | None = Field(default=None, ge=0, le=2**53)


class SignedQueueRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['sos', 'duress', 'man_down', 'scan', 'position', 'report']
    device_id: str = Field(min_length=1, max_length=100)
    client_id: str = Field(min_length=1, max_length=100)
    captured_at: str = Field(min_length=20, max_length=40)
    previous_device_time: str | None = Field(default=None, min_length=20, max_length=40)
    payload: dict[str, Any]
    signature: str = Field(pattern=r'^[0-9a-f]{64}$')

    @field_validator('captured_at', 'previous_device_time')
    @classmethod
    def aware_queue_time(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError as exc:
                raise ValueError('زمان صف باید ISO با منطقه زمانی باشد') from exc
            if parsed.tzinfo is None:
                raise ValueError('زمان صف باید منطقه زمانی داشته باشد')
        return value


class PositionBatchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    records: list[SignedQueueRecord] = Field(min_length=1, max_length=100)


class PositionBatchResult(BaseModel):
    accepted: list[PositionReceipt]
    clock_regressed_client_ids: list[str]



class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=2, max_length=1000)


class Principal(BaseModel):
    model_config = {"frozen": True}
    sub: str
    username: str
    roles: tuple[str, ...]
    zone_ids: tuple[str, ...] = ()
    contractor_id: str | None = None
    mode: Literal["keycloak", "demo"] = "keycloak"


class ErrorDetail(BaseModel):
    code: str
    message: str


class AccessError(BaseModel):
    detail: ErrorDetail | str


class AuthConfiguration(BaseModel):
    classification_label: str
    mode: Literal["keycloak", "demo"]
    issuer: str
    client_id: str
    field_client_id: str = "sepehr-field"
    admin_url: str
    idle_seconds: int


class PermissionMatrix(BaseModel):
    permissions: dict[str, list[str]]
    enforce_all: bool


class IdentityInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sub: str = Field(min_length=1, max_length=200, pattern=r"^\S+$")


class GuardRecord(BaseModel):
    id: str
    name: str
    keycloak_sub: str | None = None
    zone_id: str | None = None
    contractor_id: str | None = None


class GuardCredentialInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pin: str = Field(min_length=6, max_length=12, pattern=r"^[0-9]+$")
    duress_pin: str = Field(min_length=6, max_length=12, pattern=r"^[0-9]+$")

    @model_validator(mode="after")
    def distinct_pins(self):
        if self.pin == self.duress_pin:
            raise ValueError("رمز عادی و رمز اضطرار باید متفاوت باشند")
        return self


class EnrollmentCodeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner_sub: str = Field(min_length=1, max_length=200)
    ttl_seconds: int = Field(default=300, ge=30, le=600)


class EnrollmentCode(BaseModel):
    code: str
    expires_at: str


class DeviceEnrollmentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=16, max_length=200)
    label: str = Field(min_length=1, max_length=100)


class DeviceRecord(BaseModel):
    id: str
    label: str
    owner_sub: str
    status: Literal["active", "revoked"]
    ex_certified: bool
    registered_at: str
    last_seen: str | None = None


class EnrolledDevice(DeviceRecord):
    device_secret: str


class DeviceCertificationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ex_certified: bool


class ScopedInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    zone_id: str = Field(min_length=1, max_length=100)
    contractor_id: str = Field(min_length=1, max_length=100)


class TourRouteInput(ScopedInput):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    guard_id: str = Field(min_length=1, max_length=100)
    station_ids: list[str] = Field(default_factory=list, max_length=100)
    order_mode: Literal['fixed', 'randomized'] = 'fixed'
    fixed_first: str | None = None
    fixed_last: str | None = None
    must_precede: list[tuple[str, str]] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def valid_order(self):
        ids = self.station_ids
        if len(set(ids)) != len(ids) or (self.fixed_first and self.fixed_first not in ids) or (self.fixed_last and self.fixed_last not in ids):
            raise ValueError('ایستگاه‌های مسیر یا قید ابتدا/انتها معتبر نیستند')
        if self.fixed_first and self.fixed_first == self.fixed_last and len(ids) > 1:
            raise ValueError('ایستگاه ابتدا و انتها باید متفاوت باشند')
        if any(a not in ids or b not in ids or a == b for a, b in self.must_precede):
            raise ValueError('قید تقدم مسیر معتبر نیست')
        return self


class TourRoute(TourRouteInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    created_at: str
    coverage_mode: Literal['all', 'optimized'] = 'all'
    stations_per_tour: int | None = None
    subset_mode: Literal['shadow', 'active'] = 'shadow'


class ShiftSegment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    duration_minutes: int = Field(ge=1, le=1440)


class ShiftCycle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    on_days: int = Field(ge=1, le=365)
    off_days: int = Field(ge=1, le=365)
    anchor_date: date


class ShiftBreak(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start_offset_minutes: int = Field(ge=0, le=1440)
    duration_minutes: int = Field(ge=1, le=1440)
    label: str = Field(min_length=1, max_length=100)


class ShiftPatternInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    segments: list[ShiftSegment] = Field(min_length=1, max_length=24)
    cycle: ShiftCycle | None = None
    breaks: list[ShiftBreak] = Field(default_factory=list, max_length=24)

    @model_validator(mode='after')
    def valid_breaks(self):
        for item in self.breaks:
            if not any(item.start_offset_minutes + item.duration_minutes <= segment.duration_minutes for segment in self.segments):
                raise ValueError('استراحت باید در یکی از بخش‌های شیفت جا بگیرد')
        return self


class ShiftPattern(ShiftPatternInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    created_at: str


class TourScheduleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    route_id: str
    pattern_id: str
    first_date: date
    last_date: date
    tours_per_shift: int = Field(default=1, ge=1, le=12)


class TourSchedule(TourScheduleInput, ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    status: Literal['draft', 'approved']
    created_at: str
    approved_at: str | None = None


class ScheduledTour(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    schedule_id: str
    route_id: str
    guard_id: str
    service_date: date
    segment_index: int
    tour_number: int
    due_at: str
    ends_at: str
    station_ids: list[str]
    status: Literal['queued', 'active', 'completed', 'excused']
    warnings: list[str]
    handover_id: str | None = None
    tour_id: str | None = None
    selection_mode: Literal['all', 'optimized'] = 'all'
    proposed_station_ids: list[str] = Field(default_factory=list)
    selection_finding_id: str | None = None


class ShiftHandoverInput(ScopedInput):
    model_config = ConfigDict(extra='forbid')
    outgoing_guard_id: str
    incoming_guard_id: str
    open_items: list[str] = Field(default_factory=list, max_length=100)
    notes: str = Field(default='', max_length=2000)


class ShiftHandover(ShiftHandoverInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    acknowledged_at: str | None = None
    acknowledged_by: str | None = None
    created_at: str


class EmergencyModeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool
    reason: str = Field(min_length=3, max_length=1000)


class EmergencyMode(BaseModel):
    zone_id: str
    active: bool
    reason: str
    changed_at: str
    actor_sub: str


class DailyTourView(BaseModel):
    date: date
    walking: list[ScheduledTour]
    vehicles: list[PatrolPlan]


class TourInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    route_id: str = Field(min_length=1, max_length=100)
    scheduled_tour_id: str | None = None


class TourRecord(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    route_id: str
    guard_id: str
    owner_sub: str
    status: Literal["active", "completed"]
    started_at: str
    completed_at: str | None = None
    scheduled_tour_id: str | None = None


class CheckInInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pin: str = Field(min_length=6, max_length=12, pattern=r"^[0-9]+$")


class PinUnlockInput(CheckInInput):
    model_config = ConfigDict(extra='forbid')
    tour_id: str


class PinUnlockResult(BaseModel):
    unlocked: Literal[True] = True
    checked_at: str


class CheckInRecord(BaseModel):
    id: str
    tour_id: str
    guard_id: str
    owner_sub: str
    device_id: str
    time: str
    zone_id: str
    contractor_id: str


class TagInput(ScopedInput):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(min_length=1, max_length=100)


class TagRecord(TagInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    status: Literal["active", "revoked"]
    key_version: int


REPORT_CATEGORIES = ('security', 'safety_hse', 'operations', 'damage', 'uxo', 'drone_sighting', 'other')
RESTRICTED_REPORT_CATEGORIES = ('damage', 'uxo', 'drone_sighting')
ReportCategory = Literal['security', 'safety_hse', 'operations', 'damage', 'uxo', 'drone_sighting', 'other']
ReportAudience = Literal['security', 'hse', 'operations']
MEDIA_CONTENT_TYPES = {
    'image': ('image/jpeg', 'image/png', 'image/webp'),
    'audio': ('audio/webm', 'audio/ogg', 'audio/mp4'),
    'video': ('video/webm', 'video/mp4'),
}


class MessageAudience(BaseModel):
    model_config = ConfigDict(extra='forbid')
    guard_id: str | None = Field(default=None, min_length=1, max_length=100)
    broadcast_zone: str | None = Field(default=None, min_length=1, max_length=100)
    contractor_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def one_target(self):
        if (self.guard_id is None) == (self.broadcast_zone is None):
            raise ValueError('مخاطب پیام باید یک نگهبان یا یک محوطه باشد')
        if self.guard_id is not None and self.contractor_id is not None:
            raise ValueError('پیمانکار فقط برای اعلان محوطه تعیین می‌شود')
        return self


class FieldMessageInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tour_id: str | None = Field(default=None, min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    priority: Literal['normal', 'urgent'] = 'normal'
    audience: MessageAudience | None = None


class MessageRecipient(BaseModel):
    guard_id: str
    owner_sub: str
    acknowledged_at: str | None = None


class FieldMessage(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    tour_id: str | None
    text: str
    priority: Literal['normal', 'urgent']
    direction: Literal['to_center', 'to_guard', 'broadcast']
    owner_sub: str
    sender_sub: str
    guard_id: str | None
    created_at: str
    recipients: list[MessageRecipient]
    center_ack_at: str | None = None
    center_ack_sub: str | None = None
    escalation: Literal['operator', 'shift_supervisor', 'security_officer'] = 'operator'


class FieldMediaInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tour_id: str = Field(min_length=1, max_length=100)
    caption: str = Field(min_length=1, max_length=500)
    media_type: Literal["image", "audio", "video"]
    report_id: str | None = Field(default=None, min_length=1, max_length=100)


class MediaWatermark(BaseModel):
    captured_at_jalali: str
    guard_code: str
    station_code: str
    viewer: str
    viewed_at_jalali: str


class FieldMedia(FieldMediaInput, ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    owner_sub: str
    guard_id: str
    created_at: str
    status: Literal['metadata', 'stored', 'purged'] = 'metadata'
    device_id: str | None = None
    station_id: str | None = None
    category: ReportCategory | None = None
    content_type: str | None = None
    size: int | None = None
    sha256: str | None = None
    server_received_at: str | None = None
    legal_hold: bool = False
    incident_id: str | None = None
    retention_until: str | None = None
    purged_at: str | None = None
    exportable: bool = True
    watermark: MediaWatermark | None = None


class MediaUploadInput(FieldMediaInput):
    model_config = ConfigDict(extra='forbid')
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size: int = Field(gt=0)
    content_type: str = Field(min_length=3, max_length=100)
    client_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def matching_type(self):
        if self.content_type not in MEDIA_CONTENT_TYPES[self.media_type]:
            raise ValueError('نوع محتوا با نوع رسانه سازگار یا مجاز نیست')
        return self


class CapturePolicy(BaseModel):
    tour_id: str
    image_video_allowed: bool
    audio_allowed: Literal[True] = True
    station_id: str | None
    video_max_seconds: int
    audio_max_seconds: int
    video_bitrate_kbps: int
    audio_bitrate_kbps: int
    chunk_bytes: int
    single_upload_max_bytes: int
    max_bytes: int


class MediaUpload(BaseModel):
    id: str
    tour_id: str
    media_type: Literal['image', 'audio', 'video']
    content_type: str
    size: int
    sha256: str
    received_bytes: int
    chunk_bytes: int
    status: Literal['open', 'complete', 'failed']
    media_id: str | None = None
    created_at: str
    updated_at: str


class MediaUploadResult(BaseModel):
    upload: MediaUpload
    media: FieldMedia
    purge_local_copy: bool


class MediaAttachInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    incident_id: str = Field(min_length=1, max_length=100)


class LegalHoldInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    hold: bool
    reason: str = Field(min_length=3, max_length=500)


class FieldReportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tour_id: str = Field(min_length=1, max_length=100)
    category: ReportCategory
    text: str = Field(min_length=3, max_length=4000)
    client_id: str = Field(min_length=1, max_length=100)
    lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    lat: float | None = Field(default=None, ge=-85, le=85, allow_inf_nan=False)
    safety_acknowledged: bool = False

    @model_validator(mode='after')
    def restricted_safety(self):
        if (self.lon is None) != (self.lat is None):
            raise ValueError('طول و عرض جغرافیایی باید با هم ارسال شوند')
        if self.category in RESTRICTED_REPORT_CATEGORIES and not self.safety_acknowledged:
            raise ValueError('دستور ایمنی «نزدیک نشو، از فاصله امن گزارش کن» باید تأیید شود')
        return self


class ReportAcknowledgement(BaseModel):
    audience: ReportAudience
    sub: str
    at: str


class ReportAckInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    audience: ReportAudience


class FieldReport(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    tour_id: str
    guard_id: str
    owner_sub: str
    device_id: str
    category: ReportCategory
    text: str
    lon: float | None
    lat: float | None
    created_at: str
    audiences: list[ReportAudience]
    acknowledgements: list[ReportAcknowledgement]
    restricted: bool
    safety_instruction: str | None
    purge_local_media: bool
    media_ids: list[str]
    auth_expired: bool = False
    clock_regressed: bool = False
    offline_too_long: bool = False
    can_execute: Literal[False] = False


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal["rotate_tag_key", "revoke_tag", "delete_route", "change_classification"]
    target_id: str = Field(min_length=1, max_length=100)
    classification_label: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def classification_payload(self):
        if (self.action == "change_classification") != (self.classification_label is not None):
            raise ValueError("برچسب فقط برای درخواست تغییر طبقه‌بندی الزامی است")
        return self


class ApprovalRecord(ApprovalInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    requested_by: str
    approved_by: str | None = None
    status: Literal["pending", "approved", "rejected"]
    requested_at: str
    decided_at: str | None = None
    expected_version: str


class ExportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=150)
    media_id: str | None = Field(default=None, min_length=1, max_length=100)


class ExportAuthorization(BaseModel):
    classification_label: str
    audit_id: str
    generated_at: str


class RoleChangeEvent(BaseModel):
    time: str
    operation: str
    resource_path: str
    actor_id: str | None = None


class FieldZoneInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    points: list[list[float]] = Field(min_length=3, max_length=1000)
    media_capture_allowed: bool = True
    emergency_contacts: list[EmergencyContact] = Field(default_factory=list, max_length=20)

    @field_validator('points')
    @classmethod
    def polygon(cls, value):
        return validate_polygon(value)


class FieldZone(FieldZoneInput):
    model_config = ConfigDict(extra='ignore')
    id: str


class StationInput(ScopedInput):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    station_type: str = Field(default='checkpoint', min_length=1, max_length=80)
    sensitivity: str = Field(min_length=1, max_length=80)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    lat: float = Field(ge=-85, le=85, allow_inf_nan=False)
    hazards: list[Literal['h2s', 'flammable', 'ex_zone_1', 'ex_zone_2', 'heat', 'other']] = Field(default_factory=list, max_length=6)
    min_dwell_seconds: int = Field(default=0, ge=0, le=86400)
    two_person_required: bool = False
    media_capture_allowed: bool | None = None
    tag_mode: Literal['nfc_sun', 'nfc_counter', 'qr_hmac', 'code'] = 'qr_hmac'
    tag_uid: str | None = Field(default=None, pattern=r'^[0-9A-Fa-f]{14}$')

    @model_validator(mode='after')
    def uid_required(self):
        if self.tag_mode in ('nfc_sun', 'nfc_counter') and not self.tag_uid:
            raise ValueError('شناسه UID برای تگ NFC لازم است')
        return self


class Station(StationInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    media_capture_allowed: bool
    tag_status: Literal['planned', 'installed', 'damaged', 'revoked']
    tag_revision: int
    created_at: str


class StationTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal['number', 'choice', 'seal', 'audio']
    label: str = Field(min_length=1, max_length=200)
    required: bool = True
    min: float | None = Field(default=None, allow_inf_nan=False)
    max: float | None = Field(default=None, allow_inf_nan=False)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    options: list[str] | None = Field(default=None, min_length=1, max_length=50)
    expected_value: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def configuration(self):
        fields = {key for key in ('min', 'max', 'unit', 'options', 'expected_value') if getattr(self, key) is not None}
        expected = {'number': {'min', 'max', 'unit'}, 'choice': {'options'}, 'seal': {'expected_value'}, 'audio': set()}[self.kind]
        if fields != expected:
            raise ValueError('پیکربندی وظیفه با نوع آن سازگار نیست')
        if self.kind == 'number' and self.min > self.max:
            raise ValueError('حداقل باید کمتر یا برابر حداکثر باشد')
        if self.options and (len(set(self.options)) != len(self.options) or any(not o.strip() or len(o) > 100 for o in self.options)):
            raise ValueError('گزینه‌ها باید یکتا و غیرخالی باشند')
        return self


class StationTask(StationTaskInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    station_id: str
    created_at: str


class SealReplacement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_value: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=1000)


class SealChange(SealReplacement):
    model_config = ConfigDict(extra='ignore')
    id: str
    station_id: str
    task_id: str
    previous_value: str
    actor_sub: str
    time: str


class StationScan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    payload: str = Field(min_length=1, max_length=2000)
    lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    lat: float | None = Field(default=None, ge=-85, le=85, allow_inf_nan=False)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)
    device_time: AwareDatetime | None = None
    anchor_server_time: AwareDatetime | None = None
    anchor_device_time: AwareDatetime | None = None
    client_id: str | None = Field(default=None, min_length=1, max_length=100)
    gas_detector_confirmed: bool = False
    previous_device_time: AwareDatetime | None = None

    @model_validator(mode='after')
    def paired_anchor(self):
        if (self.anchor_server_time is None) != (self.anchor_device_time is None):
            raise ValueError('دو زمان لنگر باید با هم ارسال شوند')
        if (self.lon is None) != (self.lat is None):
            raise ValueError('طول و عرض جغرافیایی باید با هم ارسال شوند')
        return self


class TagVerification(BaseModel):
    station_id: str
    tag_revision: int
    kid: str
    assurance: Literal['قوی', 'ضعیف', 'ایستا']
    counter: int | None = None


class StationTagSheet(BaseModel):
    code: str
    svg: str
    classification_label: str
    audit_id: str


class SunProvisioning(BaseModel):
    kid: str
    uid: str
    meta_key: str
    file_key: str
    # MACInput begins at the literal tag= parameter and ends before cmac value.
    url_template: str
    ndef_hex: str
    picc_data_offset: int
    mac_input_offset: int
    mac_offset: int


class StationVisitInput(StationScan):
    model_config = ConfigDict(extra='forbid')
    tour_id: str = Field(min_length=1, max_length=100)


class ManualScanInput(StationVisitInput):
    model_config = ConfigDict(extra='forbid')
    payload: Literal['manual'] = 'manual'
    reason: str = Field(min_length=3, max_length=1000)
    uid: str | None = Field(default=None, pattern=r'^[0-9A-Fa-f]{14}$')


class ScanEvidence(BaseModel):
    tag: Literal['sun_valid', 'counter_ok', 'hmac_valid', 'uid_only', 'manual', 'replay', 'paper']
    location: Literal['verified', 'unverified', 'unavailable', 'implausible']
    sequence: Literal['in_order', 'out_of_order']
    dwell: Literal['ok', 'too_short']
    clock: Literal['ok', 'skewed', 'regressed', 'unknown']


class ScanRecord(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    method: Literal['tag', 'manual', 'paper'] = 'tag'
    station_id: str
    tour_id: str
    visit_id: str | None = None
    owner_sub: str
    device_id: str
    client_id: str | None = None
    received_at: str
    device_time: str | None = None
    lon: float | None = None
    lat: float | None = None
    accuracy_m: float | None = None
    evidence: ScanEvidence
    trust_level: Literal['high', 'medium', 'low']
    status: Literal['accepted', 'pending_review', 'rejected']
    review_sub: str | None = None
    reviewed_at: str | None = None
    reason: str = ''
    hazard_flags: list[str] = Field(default_factory=list)
    offline_flags: list[Literal['offline_too_long', 'clock_regressed']] = Field(default_factory=list)


class ManualReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approved: bool
    reason: str = Field(min_length=3, max_length=1000)


class StationVisit(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    status: Literal["active", "completed", "cancelled"] = "active"
    id: str
    station_id: str
    tour_id: str
    owner_sub: str
    device_id: str
    arrived_at: str
    completed_at: str | None = None
    second_sub: str | None = None
    assurance: Literal['قوی', 'ضعیف', 'ایستا', 'دستی']
    task_ids: list[str]
    min_dwell_seconds: int
    two_person_required: bool
    media_capture_allowed: bool
    tag_revision: int
    scan_id: str | None = None
    trust_level: Literal['high', 'medium', 'low'] | None = None
    hazard_flags: list[str] = Field(default_factory=list)
    offline_flags: list[Literal['offline_too_long', 'clock_regressed']] = Field(default_factory=list)


class StationTaskAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: str | Annotated[float, Field(strict=True, allow_inf_nan=False)] | None = None
    media_id: str | None = Field(default=None, min_length=1, max_length=100)


class StationTaskResult(BaseModel):
    id: str
    visit_id: str
    task_id: str
    value: str | float | None
    media_id: str | None
    anomaly: bool
    evidence: str
    recorded_at: str


class StationTagStatusInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tag_status: Literal['damaged']
    reason: str = Field(min_length=3, max_length=1000)


class StationVisitCancel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=3, max_length=1000)


class FieldSafetyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tour_id: str
    type: Literal['sos', 'man_down']
    client_id: str = Field(min_length=1, max_length=100)
    motionless_seconds: int | None = Field(default=None, ge=0, le=86400)
    fall_detected: bool = False


class FieldSafetyReceipt(BaseModel):
    id: str
    server_received_at: str
    incident_id: str | None = None
    operator_ack_at: str | None = None


class FieldSafetyAlert(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    tour_id: str
    guard_id: str
    owner_sub: str
    type: Literal['sos', 'man_down', 'duress']
    created_at: str
    incident_id: str | None = None
    operator_ack_at: str | None = None
    escalation: Literal['operator', 'shift_supervisor', 'security_officer']
    finding_id: str | None = None
    auth_expired: bool = False
    clock_regressed: bool = False
    rate_flagged: bool = False
    can_execute: Literal[False] = False


class MusterInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    zone_id: str
    contractor_id: str | None = None
    reason: str = Field(min_length=3, max_length=1000)


class MusterParticipant(BaseModel):
    guard_id: str
    owner_sub: str
    response: Literal['safe', 'need_help'] | None = None
    responded_at: str | None = None


class Muster(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    reason: str
    created_at: str
    actor_sub: str
    participants: list[MusterParticipant]
    unanswered_guard_ids: list[str]


class MusterNotice(BaseModel):
    id: str
    zone_id: str
    reason: str
    created_at: str
    response: Literal['safe', 'need_help'] | None = None


class MusterResponseInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    response: Literal['safe', 'need_help']


class MusterResponse(BaseModel):
    muster_id: str
    response: Literal['safe', 'need_help']
    responded_at: str


class TourReport(BaseModel):
    classification_label: str
    generated_at: str
    tours: list[TourRecord]
    checkins: list[CheckInRecord]
    station_visits: list[StationVisit]
    task_results: list[StationTaskResult]


ExceptionKind = Literal['station_missed', 'station_overdue', 'scan_low_trust', 'scan_pending_review',
                        'alarm_unacked', 'duress_unacked', 'man_down_unacked', 'device_silent',
                        'muster_open', 'message_urgent_unacked', 'integrity']


class ExceptionItem(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    kind: ExceptionKind
    severity: Literal['critical', 'high', 'medium', 'low']
    title: str
    detail: str
    since: str
    guard_id: str | None = None
    station_id: str | None = None
    source_ids: list[str]
    can_execute: Literal[False] = False


class SuspendedTour(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    scheduled_tour_id: str
    guard_id: str
    due_at: str
    ends_at: str
    station_count: int
    reason: str


class StationStatus(ScopedInput):
    model_config = ConfigDict(extra='ignore')
    station_id: str
    name: str
    status: Literal['ok', 'unverified', 'never']
    last_scan_id: str | None
    last_trust: Literal['high', 'medium', 'low'] | None
    last_scan_at: str | None
    tag_mode: str


class ExceptionBoard(BaseModel):
    classification_label: str
    generated_at: str
    generated_at_jalali: str
    items: list[ExceptionItem]
    counts: dict[str, int]
    suspended: list[SuspendedTour]
    emergency_zone_ids: list[str]
    stations: list[StationStatus]


class ReportPeriod(BaseModel):
    window_from: str
    window_to: str
    from_jalali: str
    to_jalali: str


class ComplianceTotals(BaseModel):
    planned: int
    visited: int
    verified: int
    verified_percent: float | None
    missed: int
    pending: int
    suspended: int


class TrustSummary(BaseModel):
    high: int
    medium: int
    low: int
    manual: int
    pending_review: int
    weak_tag: int
    rejected_replay: int


class ContractorLine(ComplianceTotals):
    contractor_id: str
    zone_id: str


class EmergencyLine(BaseModel):
    zone_id: str
    active: bool
    reason: str
    changed_at: str


class AuditChainHealth(BaseModel):
    valid: bool
    count: int
    scope: str


class PatrolReport(BaseModel):
    classification_label: str
    generated_at: str
    generated_at_jalali: str
    viewer: str
    period: ReportPeriod
    totals: ComplianceTotals
    trust: TrustSummary
    contractors: list[ContractorLine]
    emergency: list[EmergencyLine]
    integrity: dict[str, int]
    exceptions: dict[str, int]
    audit_chain: AuditChainHealth
    audit_id: str


class GuardCheck(BaseModel):
    scheduled_tour_id: str
    station_id: str
    due_at: str
    ends_at: str
    outcome: Literal['verified', 'visited_unverified', 'missed', 'pending', 'suspended']
    visit_id: str | None
    trust_level: Literal['high', 'medium', 'low'] | None


class GuardDetailReport(BaseModel):
    classification_label: str
    generated_at: str
    viewer: str
    guard_id: str
    guard_name: str
    zone_id: str | None
    contractor_id: str | None
    period: ReportPeriod
    checks: list[GuardCheck]
    scans: list['ScanRecord']
    totals: ComplianceTotals
    audit_id: str


class PaperScanInput(BaseModel):
    """A later entry of the printed backup patrol form; always method=paper and trust=low."""
    model_config = ConfigDict(extra='forbid')
    scheduled_tour_id: str = Field(min_length=1, max_length=200)
    station_id: str = Field(min_length=1, max_length=100)
    recorded_at: AwareDatetime
    form_serial: str = Field(min_length=1, max_length=60, pattern=r'^[0-9A-Za-z_-]+$')
    notes: str = Field(default='', max_length=1000)


class DeviceCapabilityInput(BaseModel):
    """Client-observed browser capabilities and battery for pilot measurement; no location."""
    model_config = ConfigDict(extra='forbid')
    barcode_detector: bool
    web_nfc: bool
    wake_lock: bool
    device_motion: bool
    battery_level: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    charging: bool | None = None
    auth_refresh_ok: int = Field(default=0, ge=0, le=10000)
    auth_refresh_failed: int = Field(default=0, ge=0, le=10000)
    platform: str = Field(default='', max_length=60)


class DeviceCapabilityReport(DeviceCapabilityInput):
    model_config = ConfigDict(extra='ignore')
    id: str
    device_id: str
    owner_sub: str
    reported_at: str


class PilotMetric(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str
    samples: int
    method: str


class PilotMetrics(BaseModel):
    classification_label: str
    generated_at: str
    period: ReportPeriod
    metrics: list[PilotMetric]
    manual_measurements: list[str]
    audit_id: str


class DossierEndpoint(BaseModel):
    method: str
    path: str
    authentication: Literal['public', 'device_signature', 'required', 'optional_unless_enforce_all']
    permission: str
    roles: list[str]


class DossierCrypto(BaseModel):
    purpose: str
    algorithm: str
    implementation: str


class DossierData(BaseModel):
    store: str
    description: str
    personal: bool
    retention: str
    records: int


class DossierSystem(BaseModel):
    name: str
    version: str
    hosting: str
    auth_mode: Literal['keycloak', 'demo']
    enforce_all: bool
    oidc_issuer_configured: bool


class SecurityDossier(BaseModel):
    """Facts for the AFTA security-assessment inquiry; not an assessment result."""
    generated_at: str
    generated_at_jalali: str
    classification_label: str
    organization: str
    system: DossierSystem
    endpoints: list[DossierEndpoint]
    permissions: dict[str, list[str]]
    response_headers: dict[str, str]
    settings: dict[str, Any]
    cryptography: list[DossierCrypto]
    data_inventory: list[DossierData]
    audit_chain: AuditChainHealth
    residual_risks: list[str]
    audit_id: str = ''


class StrategyTarget(BaseModel):
    id: str
    name: str
    kind: str
    target_class: str
    value: float
    bayes: BayesEstimate
    attempt_probability: float
    attacker_uncovered: float
    detection: float
    coverage: float
    attacker_utility: float
    attack_probability: float
    mandatory: bool = False
    selected: bool = False


class StrategyOutcome(BaseModel):
    defender_expected: float
    attacker_expected: float
    attacker_max: float
    expected_loss: float


class StrategyConformity(BaseModel):
    plans: int
    chi_square: float
    degrees_of_freedom: int
    max_standardized_deviation: float


class PatrolStrategy(BaseModel):
    """Optimal randomized coverage with its full arithmetic; advisory only."""
    model: Literal['stackelberg', 'quantal', 'weighted']
    resources: float
    horizon_hours: float
    threat_profile: float
    targets: list[StrategyTarget]
    attacked_target_id: str | None
    outcome: StrategyOutcome
    baselines: dict[str, StrategyOutcome]
    improvement_vs_uniform: float | None
    improvement_vs_proportional: float | None
    entropy: float
    parameters_fingerprint: str
    parameters_approved: bool
    approved_by: str | None = None
    approved_at: str | None = None
    warnings: list[str]
    conformity: StrategyConformity | None = None
    can_execute: Literal[False] = False


class PatrolGameApproval(BaseModel):
    fingerprint: str
    approved: bool
    approved_by: str | None
    approved_at: str | None


class RiskEventInput(BaseModel):
    """Historical or manual event for the Bayesian ledger; append-only and audited."""
    model_config = ConfigDict(extra='forbid')
    time: AwareDatetime
    category: Literal['theft', 'sabotage', 'intrusion', 'tampering', 'vandalism', 'other']
    lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    lat: float | None = Field(default=None, ge=-85, le=85, allow_inf_nan=False)
    target_id: str | None = Field(default=None, min_length=1, max_length=200)
    weight: float = Field(default=1.0, gt=0, le=10, allow_inf_nan=False)
    description: str = Field(min_length=3, max_length=1000)
    source_ref: str = Field(min_length=1, max_length=120)

    @model_validator(mode='after')
    def located(self):
        if (self.lon is None) != (self.lat is None):
            raise ValueError('طول و عرض جغرافیایی باید با هم ارسال شوند')
        if self.lon is None and self.target_id is None:
            raise ValueError('محل رخداد یا شناسه هدف لازم است')
        return self


class RiskEventImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    events: list[RiskEventInput] = Field(min_length=1, max_length=2000)


class RiskEvent(BaseModel):
    model_config = ConfigDict(extra='ignore')
    id: str
    source: str
    category: str
    time: str
    lon: float | None
    lat: float | None
    target_id: str | None
    weight: float
    source_ref: str
    description: str = ''


class RiskEventImportResult(BaseModel):
    created: int
    unchanged: int
    events: list[RiskEvent]


class RouteCoverageInput(BaseModel):
    """Herasat's decision for one walking route: visit all stations or an optimized subset."""
    model_config = ConfigDict(extra='forbid')
    coverage_mode: Literal['all', 'optimized']
    stations_per_tour: int | None = Field(default=None, ge=1, le=500)
    subset_mode: Literal['shadow', 'active'] = 'shadow'

    @model_validator(mode='after')
    def subset_size(self):
        if (self.coverage_mode == 'optimized') != (self.stations_per_tour is not None):
            raise ValueError('تعداد ایستگاه هر دور فقط و الزاماً برای حالت بهینه تعیین می‌شود')
        return self


PatrolPlan.model_rebuild()


class CommandGeometry(BaseModel):
    """GeoJSON geometry (WGS84, longitude first) of a spatial mission command."""
    model_config = ConfigDict(extra='forbid')
    type: Literal['Point', 'LineString', 'Polygon']
    coordinates: Any

    @model_validator(mode='after')
    def valid(self):
        if self.type == 'Point':
            validate_coordinates([self.coordinates])
        elif self.type == 'LineString':
            if not isinstance(self.coordinates, list) or len(self.coordinates) < 2 or len(self.coordinates) > 500:
                raise ValueError('خط باید بین ۲ تا ۵۰۰ نقطه داشته باشد')
            validate_coordinates(self.coordinates)
        else:
            if not isinstance(self.coordinates, list) or len(self.coordinates) != 1:
                raise ValueError('چندضلعی فرمان فقط یک حلقه بیرونی دارد')
            ring = self.coordinates[0]
            if not isinstance(ring, list) or len(ring) > 501:
                raise ValueError('حلقه چندضلعی نامعتبر است')
            validate_polygon(ring[:-1] if len(ring) > 3 and ring[0] == ring[-1] else ring)
        return self


MissionCommandType = Literal['visit_point', 'inspect_area', 'patrol_line', 'check_alarm', 'presence']
RecipientStatus = Literal['dispatched', 'delivered', 'acknowledged', 'in_progress', 'completed',
                          'rejected', 'failed', 'expired', 'cancelled']


class MissionCommandPreviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    geometry: CommandGeometry
    radius_m: float = Field(default=0, ge=0, le=20000, allow_inf_nan=False)


class CommandCandidate(BaseModel):
    asset_id: str
    name: str
    position_state: str
    lon: float | None
    lat: float | None
    observed_at: str | None
    distance_m: float | None
    inside: bool | None
    can_receive: bool
    reason: str


class MissionCommandPreview(BaseModel):
    """Who is in the area now. Only fresh positions count as inside; stale/unknown are listed apart."""
    snapshot_id: str
    eligible: list[CommandCandidate]
    needs_review: list[CommandCandidate]
    outside: list[CommandCandidate]
    cannot_receive: list[CommandCandidate]
    computed_at: str


class MissionCommandInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=8, max_length=100)
    type: MissionCommandType
    title: str = Field(min_length=3, max_length=120)
    instructions: str = Field(default='', max_length=2000)
    priority: Literal['normal', 'urgent'] = 'normal'
    geometry: CommandGeometry
    radius_m: float = Field(default=0, ge=0, le=20000, allow_inf_nan=False)
    recipients: list[str] = Field(min_length=1, max_length=100)
    snapshot_id: str = Field(min_length=8, max_length=64)
    ack_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    due_at: AwareDatetime | None = None

    @field_validator('recipients')
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('مخاطب تکراری است')
        return value


class CommandRecipient(BaseModel):
    asset_id: str
    name: str
    status: RecipientStatus
    snapshot: CommandCandidate
    delivered_at: str | None = None
    delivered_device_id: str | None = None
    acknowledged_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    note: str | None = None
    evidence: list[float] | None = None


class CommandEvent(BaseModel):
    time: str
    actor: str
    asset_id: str | None
    action: str
    from_status: str | None
    to_status: str | None
    event_id: str | None = None
    applied: bool
    detail: str = ''


class MissionCommand(BaseModel):
    """A human spatial order, distinct from a device command; can_execute is always false."""
    id: str
    revision: int
    type: MissionCommandType
    title: str
    instructions: str
    priority: Literal['normal', 'urgent']
    geometry: CommandGeometry
    radius_m: float
    status: str
    created_at: str
    created_by: str
    expires_at: str
    due_at: str | None
    overdue: bool = False
    recipients: list[CommandRecipient]
    timeline: list[CommandEvent]
    zone_id: str | None = None
    contractor_id: str | None = None
    can_execute: Literal[False] = False


class MissionCommandAction(BaseModel):
    """Field action by the addressed guard; event_id makes retries (double tap, offline resend) idempotent."""
    model_config = ConfigDict(extra='forbid')
    event_id: str = Field(min_length=8, max_length=100)
    action: Literal['acknowledge', 'reject', 'start', 'complete', 'fail']
    note: str = Field(default='', max_length=1000)
    lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    lat: float | None = Field(default=None, ge=-85, le=85, allow_inf_nan=False)

    @model_validator(mode='after')
    def reasons(self):
        if self.action in ('reject', 'fail', 'complete') and len(self.note.strip()) < 3:
            raise ValueError('برای رد، شکست یا تکمیل مأموریت توضیح لازم است')
        if (self.lon is None) != (self.lat is None):
            raise ValueError('طول و عرض جغرافیایی باید با هم ارسال شوند')
        return self


class MissionCommandCancel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=3, max_length=500)
    revision: int = Field(ge=1)


class RoadRoute(BaseModel):
    """Fastest drive over the offline road graph; access_km is the off-road leg to the nearest road node."""
    distance_km: float
    eta_minutes: float
    access_km: float
    path: list[list[float]]
    source: str
    id: str = "R1"
    label: str = "سریع‌ترین"


class RoutePlan(BaseModel):
    """Fastest route and distinct alternatives; closed hazard areas of other open incidents are avoided."""
    routes: list[RoadRoute]
    avoided_areas: int
    source: str


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    origin: list[float] = Field(min_length=2, max_length=2)
    destination: list[float] = Field(min_length=2, max_length=2)
    alternatives: int = Field(default=3, ge=1, le=3)
    avoid_areas: list[HazardArea] = Field(default_factory=list, max_length=20)

    @field_validator("origin", "destination")
    @classmethod
    def valid_point(cls, point):
        validate_coordinates([point])
        return point


class RoadNetworkStatus(BaseModel):
    source: str
    nodes: int
    edges: int
    max_snap_km: float
