"""Retention worker and database maintenance for PlantPulse telemetry platform.

Periodically deletes telemetry values older than a configurable number of days (default 30)
in batches to prevent lock contention, and executes VACUUM when the free-page ratio
exceeds a threshold (default 20%) to reclaim storage without blocking concurrent writers.
"""

import asyncio
import contextlib
import logging
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("plantpulse.retention")

DEFAULT_RETENTION_DAYS = 30
DEFAULT_BATCH_SIZE = 50000
DEFAULT_FREE_PAGE_THRESHOLD = 0.20  # 20% free pages triggers VACUUM
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


def check_free_page_ratio(conn: sqlite3.Connection) -> tuple[int, int, float]:
    """Return (freelist_count, page_count, free_ratio) for SQLite database."""
    cur = conn.cursor()
    cur.execute("PRAGMA freelist_count;")
    freelist_count = cur.fetchone()[0]
    cur.execute("PRAGMA page_count;")
    page_count = cur.fetchone()[0]
    ratio = freelist_count / max(1, page_count)
    return freelist_count, page_count, ratio


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cur.fetchone() is not None


def delete_expired_telemetry_batch(
    conn: sqlite3.Connection,
    cutoff_iso: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Delete a single batch of telemetry_values older than cutoff_iso."""
    cur = conn.execute(
        "DELETE FROM telemetry_values WHERE id IN ("
        "  SELECT id FROM telemetry_values WHERE received_at < ? LIMIT ?"
        ")",
        (cutoff_iso, batch_size),
    )
    conn.commit()
    return cur.rowcount


def delete_expired_stage_events_batch(
    conn: sqlite3.Connection,
    cutoff_iso: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Delete a single batch of stage_events older than cutoff_iso."""
    cur = conn.execute(
        "DELETE FROM stage_events WHERE id IN ("
        "  SELECT id FROM stage_events WHERE COALESCE(exited_at, entered_at) < ? LIMIT ?"
        ")",
        (cutoff_iso, batch_size),
    )
    conn.commit()
    return cur.rowcount


def delete_expired_qc_results_batch(
    conn: sqlite3.Connection,
    cutoff_iso: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Delete a single batch of qc_results older than cutoff_iso."""
    cur = conn.execute(
        "DELETE FROM qc_results WHERE id IN ("
        "  SELECT id FROM qc_results WHERE tested_at < ? LIMIT ?"
        ")",
        (cutoff_iso, batch_size),
    )
    conn.commit()
    return cur.rowcount


def delete_expired_units_batch(
    conn: sqlite3.Connection,
    cutoff_iso: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Delete a single batch of units older than cutoff_iso."""
    cur = conn.execute(
        "DELETE FROM units WHERE rowid IN ("
        "  SELECT rowid FROM units WHERE COALESCE(updated_at, created_at) < ? LIMIT ?"
        ")",
        (cutoff_iso, batch_size),
    )
    conn.commit()
    return cur.rowcount


def run_retention_cleanup(
    db_path: Path | str,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    free_page_threshold: float = DEFAULT_FREE_PAGE_THRESHOLD,
    pause_between_batches: float = 0.02,
) -> tuple[int, bool]:
    """Execute retention policy cleanup on telemetry_values, stage_events, qc_results, and units.

    Deletes expired rows in batches with brief pauses to avoid starvation of
    concurrent writers, then triggers VACUUM if free pages exceed threshold.
    Returns (total_deleted, vacuum_executed).
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    cutoff_iso = cutoff.isoformat()

    total_deleted = 0
    vacuum_executed = False

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")

        # Purge telemetry values
        if _table_exists(conn, "telemetry_values"):
            while True:
                deleted = delete_expired_telemetry_batch(conn, cutoff_iso, batch_size)
                total_deleted += deleted
                if deleted < batch_size:
                    break
                if pause_between_batches > 0:
                    time.sleep(pause_between_batches)

        # Purge child traceability events first (stage_events & qc_results)
        if _table_exists(conn, "stage_events"):
            while True:
                deleted = delete_expired_stage_events_batch(
                    conn, cutoff_iso, batch_size
                )
                total_deleted += deleted
                if deleted < batch_size:
                    break
                if pause_between_batches > 0:
                    time.sleep(pause_between_batches)

        if _table_exists(conn, "qc_results"):
            while True:
                deleted = delete_expired_qc_results_batch(conn, cutoff_iso, batch_size)
                total_deleted += deleted
                if deleted < batch_size:
                    break
                if pause_between_batches > 0:
                    time.sleep(pause_between_batches)

        # Purge parent units
        if _table_exists(conn, "units"):
            while True:
                deleted = delete_expired_units_batch(conn, cutoff_iso, batch_size)
                total_deleted += deleted
                if deleted < batch_size:
                    break
                if pause_between_batches > 0:
                    time.sleep(pause_between_batches)

        if total_deleted > 0:
            freelist_count, page_count, free_ratio = check_free_page_ratio(conn)
            logger.info(
                "Retention deleted %d rows. Freelists: %d/%d (%.1f%%)",
                total_deleted,
                freelist_count,
                page_count,
                free_ratio * 100,
            )

            if free_ratio >= free_page_threshold:
                logger.info(
                    "Free page ratio %.2f exceeds threshold %.2f; executing VACUUM...",
                    free_ratio,
                    free_page_threshold,
                )
                conn.execute("VACUUM;")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                vacuum_executed = True
                logger.info("VACUUM completed successfully.")
    finally:
        conn.close()

    return total_deleted, vacuum_executed


async def retention_worker_loop(
    db_path: Path | str,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    free_page_threshold: float = DEFAULT_FREE_PAGE_THRESHOLD,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Async background worker loop that periodically runs retention cleanup off the event loop.

    Survives unexpected exceptions (logging errors and sleeping until next interval).
    """
    logger.info(
        "Retention worker started (days=%d, interval=%.1fs, batch_size=%d, vacuum_threshold=%.2f)",
        retention_days,
        interval_seconds,
        batch_size,
        free_page_threshold,
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
        db_path: Path | str,
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
