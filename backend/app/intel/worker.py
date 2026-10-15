"""Single-process lifespan worker with an explicit list of registered capabilities."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from ..core import store
from ..field import media as field_media, safety as field_safety
from ..core.models import RuntimeSettings
from . import coverage, safety, hazard, integrity
from . import shift_report

capabilities = [coverage, safety, hazard, integrity]
logger = logging.getLogger(__name__)


def tick(now):
    """Run one deterministic tick directly, also usable without a FastAPI lifespan."""
    with store.locked_state():
        store.refresh_tracks(now_iso=now, evaluate=False)
        for capability in capabilities:
            capability.tick(now)
        field_safety.tick(now)
        field_media.tick(now)
        store.evaluate_policies(now, coverage_ready=True)
        shift_report.tick(now)


def _run_tick():
    # Take the timestamp after lock acquisition, so competing refreshes cannot
    # cause an older tick to overwrite a newer position.
    with store.locked_state():
        tick(store.now())
        return store.state["settings"]["intel_tick_seconds"]


async def run():
    while True:
        current = asyncio.create_task(asyncio.to_thread(_run_tick))
        try:
            interval = await asyncio.shield(current)
        except asyncio.CancelledError:
            # Cancellation does not stop a thread: finish its state update before
            # completing shutdown, so no writes outlive the application's lifespan.
            with suppress(Exception):
                await current
            raise
        except Exception:
            logger.exception("Intelligence worker tick failed")
            interval = RuntimeSettings.model_fields["intel_tick_seconds"].default
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from ..security.auth import auth_mode
    auth_mode()
    for year in (2023, 2024, 2026):
        if datetime(year, 7, 1, tzinfo=ZoneInfo("Asia/Tehran")).utcoffset() != timedelta(hours=3, minutes=30):
            logger.warning("Timezone data is outdated: Asia/Tehran must use UTC+03:30 since 1402")
    with store.locked_state():
        store.restore_field_state()
    enabled = os.environ.get("SEPEHR_WORKER") != "0"
    if enabled:
        await asyncio.to_thread(_run_tick)
    task = asyncio.create_task(run()) if enabled else None
    app.state.intel_worker = task
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
