# Sepehr Command — Local Demo

Design review: [implementation status and remaining gaps](docs/DESIGN-REVIEW.fa.md). The design is not fully implemented.

Start here: [راهنمای فارسی و اجرای محلی](README.fa.md).

```bash
python3 run_local.py
```

Open http://127.0.0.1:8000. First setup needs Python 3.10+ and internet for Python dependencies. The React production build is included; Node is required only for UI development.

Architecture, API contracts, SDK decisions, validation and the full capability matrix are in `docs/`.

All identities, telemetry, map geometry, commands and analytic outputs are synthetic. This is a local demonstration, not an authenticated industrial deployment.

The Omidiyeh map uses OpenStreetMap via OpenFreeMap with custom vector styling. Map tiles require internet. GIS tools include GeoJSON import/export, geographic measurements and configurable WMS/WFS overlays; see `docs/OMIDIYEH-MAP.fa.md`.

The command map has floating event cards, fullscreen, vehicle routes and timestamp-based replay. Python stores GPS history in SQLite across restarts. See [route storage and API](docs/VEHICLE-TRACKS.fa.md).
