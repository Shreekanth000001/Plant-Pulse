"""Retention worker and database maintenance for PlantPulse telemetry platform.

Periodically deletes telemetry values, stage events, QC results, and units older than
a configurable number of days (default 30) in batches to prevent lock contention.
"""

import asyncio
import contextlib
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from db import get_db_connection

logger = logging.getLogger("plantpulse.retention")

DEFAULT_RETENTION_DAYS = 30
DEFAULT_BATCH_SIZE = 50000
DEFAULT_FREE_PAGE_THRESHOLD = 0.20  # 20% free pages triggers maintenance
DEFAULT_INTERVAL_SECONDS = 86400.0  # Daily


def get_retention_days() -> int:
    try:
        return max(1, int(os.getenv("RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS))))
    except ValueError:
        return DEFAULT_RETENTION_DAYS


def is_retention_worker_enabled() -> bool:
    return os.getenv("ENABLE_RETENTION_WORKER", "false").strip().lower() in (
        "true",
        "1",
        "yes",
    )


def get_retention_interval_seconds() -> float:
    try:
        return max(
            1.0,
            float(
                os.getenv("RETENTION_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))
            ),
        )
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS


def check_free_page_ratio(conn: Any) -> tuple[int, int, float]:
    """Return free ratio (managed automatically in PostgreSQL by autovacuum)."""
    return 0, 0, 0.0


def _table_exists(conn: Any, table_name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s;",
        (table_name,),
    )
    return cur.fetchone() is not None


def delete_expired_telemetry_batch(
    conn: Any,
    cutoff_iso: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Delete a single batch of telemetry_values older than cutoff_iso."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM telemetry_values WHERE (device_timestamp, plant_id, message_id, signal_code) IN ("
        "  SELECT device_timestamp, plant_id, message_id, signal_code FROM telemetry_values WHERE received_at < %s LIMIT %s"
        ")",
        (cutoff_iso, batch_size),
    )
    conn.commit()
    return cur.rowcount


def delete_expired_stage_events_batch(
    conn: Any,
    cutoff_iso: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Delete a single batch of stage_events older than cutoff_iso."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM stage_events WHERE id IN ("
        "  SELECT id FROM stage_events WHERE COALESCE(exited_at, entered_at) < %s LIMIT %s"
        ")",
        (cutoff_iso, batch_size),
    )
    conn.commit()
    return cur.rowcount


def delete_expired_qc_results_batch(
    conn: Any,
    cutoff_iso: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Delete a single batch of qc_results older than cutoff_iso."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM qc_results WHERE id IN ("
        "  SELECT id FROM qc_results WHERE tested_at < %s LIMIT %s"
        ")",
        (cutoff_iso, batch_size),
    )
    conn.commit()
    return cur.rowcount


def delete_expired_units_batch(
    conn: Any,
    cutoff_iso: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Delete a single batch of units older than cutoff_iso."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM units WHERE (plant_id, unit_id) IN ("
        "  SELECT plant_id, unit_id FROM units WHERE COALESCE(updated_at, created_at) < %s LIMIT %s"
        ")",
        (cutoff_iso, batch_size),
    )
    conn.commit()
    return cur.rowcount


def run_retention_cleanup(
    db_path: Path | str | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    free_page_threshold: float = DEFAULT_FREE_PAGE_THRESHOLD,
    pause_between_batches: float = 0.02,
) -> tuple[int, bool]:
    """Execute retention policy cleanup on telemetry_values, stage_events, qc_results, and units.

    Deletes expired rows in batches with brief pauses to avoid starvation of
    concurrent writers. Returns (total_deleted, vacuum_executed).
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    cutoff_iso = cutoff.isoformat()

    total_deleted = 0
    vacuum_executed = False

    conn = get_db_connection(db_path)
    try:
        # Purge telemetry values
        if _table_exists(conn, "telemetry_values"):
            while True:
                deleted = delete_expired_telemetry_batch(
                    conn, cutoff_iso, batch_size=batch_size
                )
                total_deleted += deleted
                if deleted < batch_size:
                    break
                if pause_between_batches > 0:
                    time.sleep(pause_between_batches)

        # Purge stage events
        if _table_exists(conn, "stage_events"):
            while True:
                deleted = delete_expired_stage_events_batch(
                    conn, cutoff_iso, batch_size=batch_size
                )
                total_deleted += deleted
                if deleted < batch_size:
                    break
                if pause_between_batches > 0:
                    time.sleep(pause_between_batches)

        # Purge QC results
        if _table_exists(conn, "qc_results"):
            while True:
                deleted = delete_expired_qc_results_batch(
                    conn, cutoff_iso, batch_size=batch_size
                )
                total_deleted += deleted
                if deleted < batch_size:
                    break
                if pause_between_batches > 0:
                    time.sleep(pause_between_batches)

        # Purge completed or failed units older than cutoff
        if _table_exists(conn, "units"):
            while True:
                deleted = delete_expired_units_batch(
                    conn, cutoff_iso, batch_size=batch_size
                )
                total_deleted += deleted
                if deleted < batch_size:
                    break
                if pause_between_batches > 0:
                    time.sleep(pause_between_batches)

        if total_deleted > 0:
            logger.info("Retention deleted %d expired rows in batches.", total_deleted)
    finally:
        conn.close()

    return total_deleted, vacuum_executed


async def retention_worker_loop(
    db_path: Path | str | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    free_page_threshold: float = DEFAULT_FREE_PAGE_THRESHOLD,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Async background worker loop that periodically runs retention cleanup off the event loop."""
    logger.info(
        "Retention worker started (days=%d, interval=%.1fs, batch_size=%d)",
        retention_days,
        interval_seconds,
        batch_size,
    )

    while not (stop_event and stop_event.is_set()):
        try:
            deleted, vacuumed = await asyncio.to_thread(
                run_retention_cleanup,
                db_path=db_path,
                retention_days=retention_days,
                batch_size=batch_size,
                free_page_threshold=free_page_threshold,
            )
            logger.info(
                "Retention cycle completed: %d rows purged, vacuumed=%s",
                deleted,
                vacuumed,
            )
        except asyncio.CancelledError:
            logger.info("Retention worker loop cancelled.")
            raise
        except Exception:
            logger.exception(
                "Error during retention cleanup cycle; continuing worker loop."
            )

        if stop_event and stop_event.is_set():
            break

        try:
            if stop_event:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            else:
                await asyncio.sleep(interval_seconds)
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            break


class RetentionWorker:
    """Lifecycle manager for the background retention worker task."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        free_page_threshold: float = DEFAULT_FREE_PAGE_THRESHOLD,
    ) -> None:
        self.db_path = db_path
        self.retention_days = retention_days
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self.free_page_threshold = free_page_threshold
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(
                retention_worker_loop(
                    db_path=self.db_path,
                    retention_days=self.retention_days,
                    interval_seconds=self.interval_seconds,
                    batch_size=self.batch_size,
                    free_page_threshold=self.free_page_threshold,
                    stop_event=self._stop_event,
                ),
                name="retention-worker",
            )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._stop_event.set()
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
