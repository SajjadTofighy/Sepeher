#!/usr/bin/env python3
"""Concurrent load test for scan verification and position ingestion (standard library only).

Usage:
  python scripts/load_test.py --base-url https://sepehr.internal --token TOKEN --device-id DEV \
      --asset-id AST-009 --station-id STN-... --tag-payload 'SPH2:...' \
      --requests 500 --concurrency 20 [--target-p95-ms N] [--target-error-rate R]

Numeric targets are intentionally empty by default; they must be agreed with the employer.
Without targets the run only reports measurements. Run against a staging copy, never production.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


def jobs(count, asset_id, station_id, tag_payload, start=None):
    """Alternate scan verification and position reports with distinct timestamps."""
    start = start or datetime.now(timezone.utc)
    for index in range(count):
        if index % 2 == 0 and station_id and tag_payload:
            yield ("scan", f"/api/v1/tour/stations/{station_id}/verify-tag", dict(payload=tag_payload))
        else:
            stamp = (start + timedelta(milliseconds=index)).isoformat()
            yield ("position", f"/api/v1/assets/{asset_id}/positions",
                   dict(lon=49.8 + (index % 100) / 10000, lat=30.8, time=stamp, speed=5))


def http_sender(base_url, token, device_id, timeout=15):
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
    if device_id:
        headers["X-Device-Id"] = device_id

    def send(job):
        kind, path, body = job
        request = Request(base_url.rstrip("/") + path, data=json.dumps(body).encode(), headers=headers, method="POST")
        began = time.perf_counter()
        try:
            with urlopen(request, timeout=timeout) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        except (URLError, TimeoutError, OSError):
            status = 0
        return kind, status, (time.perf_counter() - began) * 1000
    return send


def run(send, work, concurrency):
    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(send, work))
    elapsed = time.perf_counter() - began
    summary = {}
    for kind in sorted({r[0] for r in results}):
        rows = [r for r in results if r[0] == kind]
        latencies = [r[2] for r in rows]
        errors = [r for r in rows if not 200 <= r[1] < 300]
        statuses = {}
        for r in rows:
            statuses[str(r[1])] = statuses.get(str(r[1]), 0) + 1
        summary[kind] = dict(requests=len(rows), errors=len(errors), error_rate=round(len(errors) / len(rows), 4),
                             p50_ms=round(percentile(latencies, 0.5), 1), p95_ms=round(percentile(latencies, 0.95), 1),
                             p99_ms=round(percentile(latencies, 0.99), 1), statuses=statuses)
    return dict(total=len(results), seconds=round(elapsed, 3),
                throughput_per_second=round(len(results) / elapsed, 1) if elapsed else None, by_kind=summary)


def evaluate(report, target_p95_ms=None, target_error_rate=None):
    failures = []
    for kind, row in report["by_kind"].items():
        if target_p95_ms is not None and row["p95_ms"] > target_p95_ms:
            failures.append(f"{kind}: p95 {row['p95_ms']} ms > {target_p95_ms}")
        if target_error_rate is not None and row["error_rate"] > target_error_rate:
            failures.append(f"{kind}: error rate {row['error_rate']} > {target_error_rate}")
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--device-id", default="")
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--station-id", default="")
    parser.add_argument("--tag-payload", default="")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--target-p95-ms", type=float, default=None)
    parser.add_argument("--target-error-rate", type=float, default=None)
    args = parser.parse_args(argv)
    report = run(http_sender(args.base_url, args.token, args.device_id),
                 list(jobs(args.requests, args.asset_id, args.station_id, args.tag_payload)), args.concurrency)
    failures = evaluate(report, args.target_p95_ms, args.target_error_rate)
    report["targets"] = dict(p95_ms=args.target_p95_ms, error_rate=args.target_error_rate,
                             note="اهداف عددی تا توافق با کارفرما خالی‌اند" if args.target_p95_ms is None else "")
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
