import asyncio
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config

from ingest import IngestEngine, sync_plant_definitions
from plant_definitions import load_plants
from retention import (
    retention_worker_loop,
    run_retention_cleanup,
)

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"


def run_alembic_upgrade(db_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    ini_path = repo_root / "alembic.ini"
    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(repo_root / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_retention.db"
    run_alembic_upgrade(db_path)

    plants = load_plants(PLANTS_DIR)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    sync_plant_definitions(conn, plants)
    conn.close()

    return db_path


def test_retention_deletes_expired_rows_and_keeps_recent(test_db):
    """Criterion: Deletes rows older than cutoff (e.g. 30 days) in batches and keeps recent rows."""
    now = datetime.now(UTC)
    old_ts = (now - timedelta(days=45)).isoformat()
    recent_ts = (now - timedelta(days=5)).isoformat()

    conn = sqlite3.connect(test_db)
    # Insert 15 expired rows and 10 recent rows
    rows = []
    for i in range(15):
        rows.append(
            (
                "plant_demo_membrane",
                "hm_01",
                "mold_temp_actual",
                old_ts,
                old_ts,
                f"old_msg_{i}",
                65.0,
                None,
            )
        )
    for i in range(10):
        rows.append(
            (
                "plant_demo_membrane",
                "hm_01",
                "mold_temp_actual",
                recent_ts,
                recent_ts,
                f"new_msg_{i}",
                65.5,
                None,
            )
        )

    conn.executemany(
        "INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num, value_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    deleted, _vacuumed = run_retention_cleanup(
        db_path=test_db, retention_days=30, batch_size=5, free_page_threshold=0.20
    )

    assert deleted == 15

    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM telemetry_values WHERE message_id LIKE 'old_msg_%'"
    )
    old_count = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM telemetry_values WHERE message_id LIKE 'new_msg_%'"
    )
    recent_count = cur.fetchone()[0]
    conn.close()

    assert old_count == 0
    assert recent_count == 10


def test_retention_vacuum_shrinks_database_file(test_db):
    """Criterion: VACUUM reclaims disk space after large batch deletions exceeding free-page threshold."""
    now = datetime.now(UTC)
    old_ts = (now - timedelta(days=40)).isoformat()

    conn = sqlite3.connect(test_db)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # Populate 30,000 rows to create a measurable file size (~7-8 MB)
    batch = []
    for i in range(30000):
        batch.append(
            (
                "plant_demo_membrane",
                "hm_01",
                "mold_temp_actual",
                old_ts,
                old_ts,
                f"shrink_msg_{i}",
                65.0,
                "x" * 128,  # Pad text so pages fill quickly
            )
        )
        if len(batch) >= 5000:
            conn.executemany(
                "INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num, value_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            conn.commit()
            batch = []

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.close()

    size_before = os.path.getsize(test_db)

    # Run retention cleanup with 10k batch size and free-page threshold 0.20
    deleted, vacuumed = run_retention_cleanup(
        db_path=test_db, retention_days=30, batch_size=10000, free_page_threshold=0.20
    )

    assert deleted == 30000
    assert vacuumed is True

    size_after = os.path.getsize(test_db)
    assert size_after < size_before


def make_valid_payload(
    message_id: str = "msg-001",
    plant_id: str = "plant_demo_membrane",
    asset_id: str = "hm_01",
    timestamp: datetime | None = None,
    metrics: dict | None = None,
) -> dict:
    ts = timestamp or datetime.now(UTC)
    return {
        "schema_version": "1.0",
        "message_id": message_id,
        "plant_id": plant_id,
        "asset_id": asset_id,
        "device_timestamp": ts.isoformat(),
        "payload_type": "telemetry",
        "payload": {
            "status": "RUNNING",
            "metrics": metrics
            or {
                "mold_temperature_actual": 65.2,
                "mold_temperature_setpoint": 65.0,
                "vibration_mms": 2.14,
            },
        },
    }


@pytest.mark.anyio
async def test_real_ingest_engine_writes_during_retention_cleanup(test_db):
    """Criterion: Real IngestEngine processes and commits messages concurrently while retention cleanup & VACUUM runs."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(
        db_path=test_db, plants=plants, batch_size=10, flush_interval_seconds=0.05
    )
    await engine.start()

    now = datetime.now(UTC)
    old_ts = (now - timedelta(days=50)).isoformat()

    # Pre-populate 15,000 expired rows
    conn = sqlite3.connect(test_db)
    conn.execute("PRAGMA busy_timeout=5000;")
    rows = [
        (
            "plant_demo_membrane",
            "hm_01",
            "mold_temperature_actual",
            old_ts,
            old_ts,
            f"bg_expired_{i}",
            65.0,
            "padding" * 10,
        )
        for i in range(15000)
    ]
    conn.executemany(
        "INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num, value_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    write_latencies = []
    write_errors = []
    stop_event = asyncio.Event()

    async def ingest_writer():
        idx = 0
        topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
        while not stop_event.is_set():
            t0 = time.time()
            payload = make_valid_payload(message_id=f"concurrent_msg_{idx}")
            try:
                accepted = await engine.enqueue(topic, payload)
                if not accepted:
                    write_errors.append(f"Message {idx} not accepted by queue")
                write_latencies.append(time.time() - t0)
            except (sqlite3.Error, RuntimeError, ValueError) as e:
                write_errors.append(str(e))
            idx += 1
            await asyncio.sleep(0.005)

    writer_task = asyncio.create_task(ingest_writer())

    # Run retention cleanup in background thread
    deleted, _vacuumed = await asyncio.to_thread(
        run_retention_cleanup,
        db_path=test_db,
        retention_days=30,
        batch_size=2000,
        free_page_threshold=0.20,
    )

    # Let writer complete at least 35 writes
    while len(write_latencies) < 35:
        await asyncio.sleep(0.01)

    stop_event.set()
    await writer_task
    await engine.stop()

    assert deleted == 15000
    assert len(write_errors) == 0, f"Ingest errors during cleanup: {write_errors}"
    assert len(write_latencies) >= 35
    max_latency_ms = max(write_latencies) * 1000
    print(
        f"\n[Bench] Max ingest write latency during retention cleanup: {max_latency_ms:.1f}ms across {len(write_latencies)} writes"
    )

    # Verify concurrent messages were committed into telemetry_values
    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM telemetry_values WHERE message_id LIKE 'concurrent_msg_%'"
    )
    committed_concurrent = cur.fetchone()[0]
    conn.close()
    assert committed_concurrent >= 35 * 3  # each payload produces 3 metrics


@pytest.mark.anyio
async def test_retention_worker_loop_survives_exception(test_db):
    """Criterion: Retention worker loop logs exceptions and continues running without crashing."""
    calls = []

    def flaky_cleanup(*args, **kwargs):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("Simulated temporary database lock")
        return (10, False)

    stop_event = asyncio.Event()

    with patch("retention.run_retention_cleanup", side_effect=flaky_cleanup):
        # Run worker with 0.05s interval
        worker_task = asyncio.create_task(
            retention_worker_loop(
                db_path=test_db,
                retention_days=30,
                interval_seconds=0.05,
                stop_event=stop_event,
            )
        )

        # Wait for at least 2 cycles
        for _ in range(30):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.02)

        stop_event.set()
        await worker_task

    assert len(calls) >= 2, (
        f"Worker loop did not continue after exception! Calls: {calls}"
    )


def test_retention_deletes_expired_traceability_and_keeps_recent(test_db):
    """Retention cleanup deletes expired units, stage_events, and qc_results while keeping recent ones."""
    now = datetime.now(UTC)
    old_ts = (now - timedelta(days=45)).isoformat()
    recent_ts = (now - timedelta(days=5)).isoformat()

    conn = sqlite3.connect(test_db)
    conn.execute("PRAGMA foreign_keys = ON")
    # Insert old and recent units
    conn.execute(
        "INSERT INTO units (plant_id, unit_id, status, created_at, updated_at) VALUES (?, ?, 'passed', ?, ?)",
        ("plant_demo_membrane", "unit_old_ret_1", old_ts, old_ts),
    )
    conn.execute(
        "INSERT INTO units (plant_id, unit_id, status, created_at, updated_at) VALUES (?, ?, 'in_progress', ?, ?)",
        ("plant_demo_membrane", "unit_recent_ret_1", recent_ts, recent_ts),
    )
    # Insert old and recent stage events
    conn.execute(
        "INSERT INTO stage_events (plant_id, unit_id, machine_code, message_id, outcome, readings, entered_at, exited_at) VALUES (?, ?, 'hm_01', 'msg_old_stg_1', 'ok', '{}', ?, ?)",
        ("plant_demo_membrane", "unit_old_ret_1", old_ts, old_ts),
    )
    conn.execute(
        "INSERT INTO stage_events (plant_id, unit_id, machine_code, message_id, outcome, readings, entered_at, exited_at) VALUES (?, ?, 'hm_01', 'msg_rec_stg_1', 'ok', '{}', ?, ?)",
        ("plant_demo_membrane", "unit_recent_ret_1", recent_ts, recent_ts),
    )
    # Insert old and recent qc results
    conn.execute(
        "INSERT INTO qc_results (plant_id, unit_id, machine_code, message_id, outcome, probability, tested_at) VALUES (?, ?, 'qc_01', 'msg_old_qc_1', 'pass', 1.0, ?)",
        ("plant_demo_membrane", "unit_old_ret_1", old_ts),
    )
    conn.execute(
        "INSERT INTO qc_results (plant_id, unit_id, machine_code, message_id, outcome, probability, tested_at) VALUES (?, ?, 'qc_01', 'msg_rec_qc_1', 'pass', 1.0, ?)",
        ("plant_demo_membrane", "unit_recent_ret_1", recent_ts),
    )
    conn.commit()
    conn.close()

    deleted, _vacuumed = run_retention_cleanup(
        db_path=test_db, retention_days=30, batch_size=5
    )
    assert deleted == 3

    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM units WHERE unit_id = 'unit_old_ret_1'")
    assert cur.fetchone()[0] == 0, "Expired unit was not deleted by retention cleanup"
    cur.execute("SELECT COUNT(*) FROM units WHERE unit_id = 'unit_recent_ret_1'")
    assert cur.fetchone()[0] == 1, "Recent unit was incorrectly deleted"

    cur.execute("SELECT COUNT(*) FROM stage_events WHERE unit_id = 'unit_old_ret_1'")
    assert cur.fetchone()[0] == 0, (
        "Expired stage event was not deleted by retention cleanup"
    )
    cur.execute("SELECT COUNT(*) FROM stage_events WHERE unit_id = 'unit_recent_ret_1'")
    assert cur.fetchone()[0] == 1, "Recent stage event was incorrectly deleted"

    cur.execute("SELECT COUNT(*) FROM qc_results WHERE unit_id = 'unit_old_ret_1'")
    assert cur.fetchone()[0] == 0, (
        "Expired qc result was not deleted by retention cleanup"
    )
    cur.execute("SELECT COUNT(*) FROM qc_results WHERE unit_id = 'unit_recent_ret_1'")
    assert cur.fetchone()[0] == 1, "Recent qc result was incorrectly deleted"
    conn.close()
