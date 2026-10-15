"""Entirely synthetic records and schematic geography; no real personnel or infrastructure."""

from datetime import datetime, timedelta, timezone

from .models import RuntimeSettings

from ..intel.geo import derive_segments

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def seed():
    now = datetime.now(timezone.utc)

    def ago(minutes):
        return (now - timedelta(minutes=minutes)).isoformat()

    assets = []
    points = [
        (49.78, 30.76),
        (49.86, 30.80),
        (49.91, 30.72),
        (49.72, 30.69),
        (49.99, 30.83),
        (49.67, 30.84),
        (49.83, 30.65),
        (50.05, 30.73),
        (49.95, 30.92),
        (49.73, 30.94),
        (49.87, 30.88),
        (50.10, 30.88),
    ]
    for i, (lon, lat) in enumerate(points):
        assets.append(
            dict(
                id=f"AST-{i + 1:03}",
                name=(f"گشت {12 + i}" if i < 8 else f"تیم میدانی {i - 7}").translate(PERSIAN_DIGITS),
                kind="vehicle" if i < 8 else "person",
                zone_id="Z1" if i >= 8 else None,
                contractor_id="SCHEMATIC" if i >= 8 else None,
                keycloak_sub=None,
                status="offline" if i == 5 else "warning" if i in [2, 8] else "online",
                lon=lon,
                lat=lat,
                speed=[42, 0, 38, 56, 24, 0, 45, 31, 4, 0, 5, 3][i],
                battery=92 - i * 4,
                signal=0 if i == 5 else 4 - i % 3,
                field=["آغاجاری", "کرنج", "پارسی"][i % 3],
                mission="حفاظت پیرامونی" if i % 2 == 0 else "بازدید ایستگاه‌های گشت",
                unit="patrol" if i < 8 else "field",
                patrol_base=[lon, lat] if i < 8 else None,
                operator=f"اپراتور نمونه {i + 1}",
                sim=f"09•• ••• {4100 + i}",
                carrier="همراه اول" if i % 2 == 0 else "ایرانسل",
                firmware="2.4.1",
                # Schematic protocol families only; no real device inventory.
                device_profile=["concox_gt06", "coban_tk103", "teltonika_fmb"][i % 3] if i < 8 else "generic_data",
                last_seen=ago(18 if i == 5 else 0),
                capabilities=[
                    "position",
                    "ping",
                    "interval",
                    "restart",
                    "beacon",
                    "diagnostics",
                ] + (["sos"] if i in (0, 2, 9) else []),
                track=[
                    {
                        "lon": lon - 0.03 + j * 0.006,
                        "lat": lat - 0.012 + j * 0.0024,
                        "time": ago(30 - j * 6),
                    }
                    for j in range(6)
                ],
            )
        )
    incidents = []
    for i, (title, sev, zone, asset) in enumerate(
        [
            ("ورود به محدوده حفاظت‌شده", "critical", "حریم تأسیسات شرقی", 2),
            ("قطع ارتباط خارج از پوشش ضعیف", "high", "مسیر گشت شمالی", 5),
            ("انحراف از مسیر مأموریت", "high", "جاده دسترسی جنوبی", 6),
            ("توقف بیش از زمان مجاز", "medium", "ایستگاه بازرسی شماره ۳", 1),
            ("افت سطح باتری نیروی میدانی", "low", "محدوده پارسی", 8),
        ]
    ):
        a = assets[asset]
        incidents.append(
            dict(
                id=f"INC-{824 + i}",
                title=title,
                severity=sev,
                status="detected" if i < 3 else "confirmed",
                zone=zone,
                asset_id=a["id"],
                lon=a["lon"] + 0.007,
                lat=a["lat"] + 0.006,
                created_at=ago(3 + i * 4),
                assigned_to=None,
                description="رخداد آزمایشی بر اساس سیاست نمونه ایجاد شده است. موقعیت و مشخصات، واقعی نیستند.",
                timeline=[
                    {
                        "time": ago(3 + i * 4),
                        "action": "کشف رخداد و تشکیل پرونده",
                        "actor": "موتور سیاست نمونه",
                    }
                ],
            )
        )
    zones = [
        dict(
            id="Z1",
            name="حریم تأسیسات شرقی",
            risk="high",
            points=[
                [49.86, 30.68],
                [49.99, 30.70],
                [50.01, 30.80],
                [49.91, 30.84],
                [49.85, 30.77],
            ],
        ),
        dict(
            id="Z2",
            name="ناحیه عملیاتی شمال",
            risk="medium",
            points=[
                [49.64, 30.84],
                [49.73, 30.98],
                [49.89, 30.97],
                [49.94, 30.89],
                [49.81, 30.82],
            ],
        ),
        dict(
            id="Z3",
            name="حوزه گشت جنوبی",
            risk="low",
            points=[
                [49.69, 30.61],
                [49.86, 30.61],
                [49.91, 30.69],
                [49.79, 30.76],
                [49.67, 30.70],
            ],
        ),
    ]
    policies = [
        dict(
            id="POL-01",
            name="ورود به محدوده حفاظت‌شده",
            zone="Z1",
            subject="vehicle",
            condition="geofence_entry",
            threshold=1,
            schedule="22:00–06:00",
            action="create_incident",
            severity="critical",
            status="active",
            version=3,
            matches=12,
            false_positives=1,
            approver="سرپرست نمونه",
        ),
        dict(
            id="POL-02",
            name="قطع ارتباط در محدوده حساس",
            zone="Z2",
            subject="all",
            condition="connection_lost",
            threshold=10,
            schedule="تمام شبانه‌روز",
            action="create_incident",
            severity="high",
            status="shadow",
            version=2,
            matches=8,
            false_positives=2,
            approver=None,
        ),
        dict(
            id="POL-03",
            name="انحراف از مسیر مأموریت",
            zone="Z3",
            subject="vehicle",
            condition="route_deviation",
            threshold=500,
            schedule="تمام شبانه‌روز",
            action="create_incident",
            severity="high",
            status="draft",
            version=1,
            matches=6,
            false_positives=0,
            approver="سرپرست نمونه",
        ),
        dict(
            id="POL-04",
            name="توقف غیرعادی در مسیر گشت",
            zone="Z1",
            subject="vehicle",
            condition="long_stop",
            threshold=15,
            schedule="تمام شبانه‌روز",
            action="create_incident",
            severity="medium",
            status="draft",
            version=1,
            matches=0,
            false_positives=0,
            approver=None,
        ),
    ]
    for index, zone in enumerate(zones):
        for offset, condition, name, schedule in (
            (0, "unknown_vehicle", "خودروی سنگین خارج از فهرست مجاز در شب", "22:00–06:00"),
            (1, "camera_event", "تکرار پلاک در دوربین‌های حساس", "تمام شبانه‌روز"),
        ):
            policies.append(dict(id=f"POL-{6 + index * 2 + offset:02}", name=name, zone=zone["id"],
                subject="vehicle", condition=condition, threshold=2 if offset else 1, schedule=schedule,
                action="create_incident", severity="high", status="shadow", version=1, matches=0,
                false_positives=0, approver=None))
    policies.append(dict(
        id="POL-05", name="دکمه اضطراری تجهیزات مجاز", zone="Z2", subject="all",
        condition="sos", threshold=1, schedule="تمام شبانه‌روز", action="create_incident",
        severity="critical", status="active", version=1, matches=0, false_positives=0,
        approver="سرپرست نمونه",
    ))
    missions = [
        dict(
            id=f"MSN-{101 + i}",
            name=n,
            asset_id=assets[i]["id"],
            zone=zones[i % 3]["name"],
            status="active",
            progress=progress,
            checkpoints=[
                dict(name=f"ایستگاه {j + 1}", visited=j < int(progress / 25))
                for j in range(4)
            ],
        )
        for i, (n, progress) in enumerate(
            [
                ("گشت پیرامونی شرق", 75),
                ("بازدید گیت‌های عملیاتی", 50),
                ("پایش مسیر خطوط لوله", 25),
                ("پوشش محور جنوبی", 50),
            ]
        )
    ]
    settings = RuntimeSettings(
        intel_emergency_contacts=[
            dict(name="اتاق کنترل نمونه", role="هماهنگی حراست", phone="DEMO-CONTROL-001"),
            dict(name="پشتیبان نمونه", role="سرپرست گشت", phone="DEMO-PATROL-002"),
        ],
        # Demo showcases an active policy; production defaults must start in shadow.
        shadow_mode=False,
    ).model_dump()
    cameras = [
        dict(
            id=f"CAM-{32 + i}",
            name=n,
            zone=zones[i % 3]["name"],
            lon=lo,
            lat=la,
            status="offline" if i == 3 else "online",
            analysis=an,
        )
        for i, (n, lo, la, an) in enumerate(
            [
                ("دوربین پیرامونی شرق", 49.91, 30.76, "ورود غیرمجاز"),
                ("گیت ورودی شمال", 49.74, 30.91, "پلاک‌خوانی"),
                ("محوطه تأسیسات", 49.83, 30.67, "آتش و دود"),
                ("محور دسترسی غرب", 49.66, 30.79, "عبور از خط"),
            ]
        )
    ]
    # Schematic synthetic layers only. The first two lines cross demo patrol
    # bases/loops; the third line and remote facilities are outside every beat.
    pipelines = [
        dict(id="PIPE-001", name="خط لوله شماتیک غرب", field="آغاجاری",
             points=[[49.735, 30.76], [49.78, 30.76], [49.805, 30.775]]),
        dict(id="PIPE-002", name="خط لوله شماتیک میانی", field="کرنج",
             points=[[49.82, 30.80], [49.86, 30.80], [49.88, 30.81]]),
        dict(id="PIPE-003", name="خط لوله شماتیک دورافتاده", field="پارسی",
             points=[[50.16, 30.63], [50.19, 30.65], [50.22, 30.66]]),
    ]
    facilities = [
        dict(id="FAC-001", name="چاه شماتیک غرب", kind="well", lon=49.78, lat=30.76,
             radius_m=150, unmanned=True, field="آغاجاری"),
        dict(id="FAC-002", name="ایستگاه شماتیک میانی", kind="station", lon=49.86, lat=30.80,
             radius_m=200, unmanned=False, field="کرنج"),
        dict(id="FAC-003", name="کارخانه شماتیک دورافتاده", kind="plant", lon=50.20, lat=30.65,
             radius_m=250, unmanned=True, field="پارسی"),
        dict(id="FAC-004", name="منیفولد شماتیک دورافتاده", kind="manifold", lon=50.18, lat=30.62,
             radius_m=100, unmanned=True, field="آغاجاری"),
    ]
    # Schematic access attributes; missing values intentionally exercise neutral scoring.
    for row, road, village, heavy in zip(pipelines, [120, 500, None], [800, 1200, None], [True, False, None]):
        row.update(road_distance_m=road, village_distance_m=village, heavy_vehicle_access=heavy)
    for row, road, village, heavy in zip(facilities, [80, 250, None, 900], [700, 400, None, 1800], [True, True, None, False]):
        row.update(road_distance_m=road, village_distance_m=village, heavy_vehicle_access=heavy)
    return dict(
        pipelines=pipelines,
        facilities=facilities,
        segments=derive_segments(pipelines),
        findings=[],
        device_events=[],
        pressure_events=[],
        plate_reads=[],
        intel={"latches": {}},
        settings=settings,
        cameras=cameras,
        assets=assets,
        incidents=incidents,
        zones=zones,
        policies=policies,
        missions=missions,
        patrol_plans=[],
        commands=[],
        audit=[],
        alerts=[],
        sim={},
        engine={},
    )
