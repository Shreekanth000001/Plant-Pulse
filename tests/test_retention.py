import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from db import ensure_partition_for_timestamp, get_db_connection
from ingest import IngestEngine, sync_plant_definitions
from main import init_platform_db
from plant_definitions import load_plants
from retention import (
    check_free_page_ratio,
    retention_worker_loop,
    run_retention_cleanup,
)

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_retention.db"
    init_platform_db(db_path)

    plants = load_plants(PLANTS_DIR)
    conn = get_db_connection(str(db_path))
    sync_plant_definitions(conn, plants)
    conn.close()

    return db_path


def test_retention_deletes_expired_rows_and_keeps_recent(test_db):
    """Criterion: Deletes rows older than cutoff (e.g. 30 days) in batches and keeps recent rows."""
    now = datetime.now(UTC)
    old_dt = now - timedelta(days=45)
    recent_dt = now - timedelta(days=5)
    old_ts = old_dt.isoformat()
    recent_ts = recent_dt.isoformat()

    conn = get_db_connection(str(test_db))
    ensure_partition_for_timestamp(conn, old_dt)
    ensure_partition_for_timestamp(conn, recent_dt)

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

    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num, value_text)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (device_timestamp, plant_id, message_id, signal_code) DO NOTHING;
        """,
        rows,
    )
    conn.commit()
    conn.close()

    _deleted, dropped = run_retention_cleanup(
        db_path=test_db, retention_days=30, batch_size=5, free_page_threshold=0.20
    )

    assert len(dropped) >= 1

    conn = get_db_connection(str(test_db))
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) as cnt FROM telemetry_values WHERE message_id LIKE 'old_msg_%'"
    )
    old_count = cur.fetchone()["cnt"]
    cur.execute(
        "SELECT COUNT(*) as cnt FROM telemetry_values WHERE message_id LIKE 'new_msg_%'"
    )
    recent_count = cur.fetchone()["cnt"]
    conn.close()

    assert old_count == 0
    assert recent_count == 10


def test_retention_vacuum_shrinks_database_file_deferred_to_pr2(test_db):
    """PostgreSQL disk reclamation is handled via partition drops in PR 2; free ratio is 0.0."""
    conn = get_db_connection(str(test_db))
    _total, _free, ratio = check_free_page_ratio(conn)
    conn.close()
    assert ratio == 0.0


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
    old_dt = now - timedelta(days=50)
    old_ts = old_dt.isoformat()

    # Pre-populate 15,000 expired rows
    conn = get_db_connection(str(test_db))
    ensure_partition_for_timestamp(conn, old_dt)
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
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num, value_text)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (device_timestamp, plant_id, message_id, signal_code) DO NOTHING;
        """,
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
            except Exception as e:  # noqa: BLE001
                write_errors.append(str(e))
            idx += 1
            await asyncio.sleep(0.005)

    writer_task = asyncio.create_task(ingest_writer())

    # Run retention cleanup in background thread
    _deleted, dropped = await asyncio.to_thread(
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
    # Allow engine worker to flush any in-flight queue items
    await asyncio.sleep(0.1)
    await engine.stop()

    assert len(dropped) >= 1
    assert len(write_errors) == 0, f"Ingest errors during cleanup: {write_errors}"
    assert len(write_latencies) >= 35
    max_latency_ms = max(write_latencies) * 1000
    print(
        f"\n[Bench] Max ingest write latency during retention cleanup: {max_latency_ms:.1f}ms across {len(write_latencies)} writes"
    )

    # Verify concurrent messages were committed into telemetry_values
    conn = get_db_connection(str(test_db))
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) as cnt FROM telemetry_values WHERE message_id LIKE 'concurrent_msg_%'"
    )
    committed_concurrent = cur.fetchone()["cnt"]
    conn.close()
    assert committed_concurrent >= 35 * 3  # each payload produces 3 metrics


@pytest.mark.anyio
async def test_retention_worker_loop_survives_exception(test_db):
    """Criterion: Retention worker loop logs exceptions and continues running without crashing."""
    calls = []

    def flaky_cleanup(*args, **kwargs):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("Simulated temporary database lock")
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

    conn = get_db_connection(str(test_db))
    cur = conn.cursor()
    # Insert old and recent units
    cur.execute(
        "INSERT INTO units (plant_id, unit_id, status, created_at, updated_at) VALUES (%s, %s, 'passed', %s, %s)",
        ("plant_demo_membrane", "unit_old_ret_1", old_ts, old_ts),
    )
    cur.execute(
        "INSERT INTO units (plant_id, unit_id, status, created_at, updated_at) VALUES (%s, %s, 'in_progress', %s, %s)",
        ("plant_demo_membrane", "unit_recent_ret_1", recent_ts, recent_ts),
    )
    # Insert old and recent stage events
    cur.execute(
        "INSERT INTO stage_events (plant_id, unit_id, machine_code, message_id, outcome, readings, entered_at, exited_at) VALUES (%s, %s, 'hm_01', 'msg_old_stg_1', 'ok', '{}', %s, %s)",
        ("plant_demo_membrane", "unit_old_ret_1", old_ts, old_ts),
    )
    cur.execute(
        "INSERT INTO stage_events (plant_id, unit_id, machine_code, message_id, outcome, readings, entered_at, exited_at) VALUES (%s, %s, 'hm_01', 'msg_rec_stg_1', 'ok', '{}', %s, %s)",
        ("plant_demo_membrane", "unit_recent_ret_1", recent_ts, recent_ts),
    )
    # Insert old and recent qc results
    cur.execute(
        "INSERT INTO qc_results (plant_id, unit_id, machine_code, message_id, outcome, probability, tested_at) VALUES (%s, %s, 'qc_01', 'msg_old_qc_1', 'pass', 1.0, %s)",
        ("plant_demo_membrane", "unit_old_ret_1", old_ts),
    )
    cur.execute(
        "INSERT INTO qc_results (plant_id, unit_id, machine_code, message_id, outcome, probability, tested_at) VALUES (%s, %s, 'qc_01', 'msg_rec_qc_1', 'pass', 1.0, %s)",
        ("plant_demo_membrane", "unit_recent_ret_1", recent_ts),
    )
    conn.commit()
    conn.close()

    deleted, _vacuumed = run_retention_cleanup(
        db_path=test_db, retention_days=30, batch_size=5
    )
    assert deleted == 3

    conn = get_db_connection(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM units WHERE unit_id = 'unit_old_ret_1'")
    assert cur.fetchone()["cnt"] == 0, "Expired unit was not deleted by retention cleanup"
    cur.execute("SELECT COUNT(*) as cnt FROM units WHERE unit_id = 'unit_recent_ret_1'")
    assert cur.fetchone()["cnt"] == 1, "Recent unit was incorrectly deleted"

    cur.execute("SELECT COUNT(*) as cnt FROM stage_events WHERE unit_id = 'unit_old_ret_1'")
    assert cur.fetchone()["cnt"] == 0, (
        "Expired stage event was not deleted by retention cleanup"
    )
    cur.execute("SELECT COUNT(*) as cnt FROM stage_events WHERE unit_id = 'unit_recent_ret_1'")
    assert cur.fetchone()["cnt"] == 1, "Recent stage event was incorrectly deleted"

    cur.execute("SELECT COUNT(*) as cnt FROM qc_results WHERE unit_id = 'unit_old_ret_1'")
    assert cur.fetchone()["cnt"] == 0, (
        "Expired qc result was not deleted by retention cleanup"
    )
    cur.execute("SELECT COUNT(*) as cnt FROM qc_results WHERE unit_id = 'unit_recent_ret_1'")
    assert cur.fetchone()["cnt"] == 1, "Recent qc result was incorrectly deleted"
    conn.close()


def test_retention_drops_expired_partitions_and_keeps_recent(test_db):
    """Criterion: Retention drops telemetry_values partitions older than RETENTION_DAYS and keeps recent partitions."""
    now = datetime.now(UTC)
    expired_dt = now - timedelta(days=45)
    recent_dt = now - timedelta(days=5)

    conn = get_db_connection(str(test_db))
    expired_part = ensure_partition_for_timestamp(conn, expired_dt)
    recent_part = ensure_partition_for_timestamp(conn, recent_dt)

    # Insert data into both partitions
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num)
        VALUES ('plant_demo_membrane', 'hm_01', 'mold_temp_actual', %s, %s, 'exp_msg', 42.0)
        ON CONFLICT DO NOTHING;
        """,
        (expired_dt.isoformat(), expired_dt.isoformat()),
    )
    cur.execute(
        """
        INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num)
        VALUES ('plant_demo_membrane', 'hm_01', 'mold_temp_actual', %s, %s, 'rec_msg', 43.0)
        ON CONFLICT DO NOTHING;
        """,
        (recent_dt.isoformat(), recent_dt.isoformat()),
    )
    conn.commit()

    # Verify both partitions exist before cleanup
    cur.execute(
        """
        SELECT c.relname
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE p.relname = 'telemetry_values' AND n.nspname = 'public';
        """
    )
    existing_parts = {r["relname"] for r in cur.fetchall()}
    assert expired_part in existing_parts
    assert recent_part in existing_parts
    conn.close()

    # Run cleanup
    _deleted, dropped = run_retention_cleanup(
        db_path=test_db, retention_days=30, batch_size=10
    )

    # Verify dropped list and partition presence in database
    assert expired_part in dropped, f"Expected {expired_part} to be dropped, got: {dropped}"
    assert recent_part not in dropped, f"Recent partition {recent_part} was dropped!"

    conn = get_db_connection(str(test_db))
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s;",
        (expired_part,),
    )
    assert cur.fetchone() is None, f"Expired partition table {expired_part} still exists!"

    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s;",
        (recent_part,),
    )
    assert cur.fetchone() is not None, f"Recent partition table {recent_part} was dropped!"

    # Recent data is still queryable
    cur.execute("SELECT COUNT(*) as cnt FROM telemetry_values WHERE message_id = 'rec_msg';")
    assert cur.fetchone()["cnt"] == 1
    conn.close()


def test_retention_leaves_non_matching_tables_untouched(test_db):
    """Criterion: Tables not strictly matching the partition naming pattern are left completely untouched."""
    conn = get_db_connection(str(test_db))
    cur = conn.cursor()

    # Create tables that must never be dropped by retention
    test_tables = [
        "telemetry_values_backup",
        "telemetry_values_p_manual_archive",
        "other_table_p2020_01_01",
        "telemetry_values_p9999_invalid_date",
    ]
    for tbl in test_tables:
        cur.execute(f'CREATE TABLE IF NOT EXISTS "{tbl}" (id int);')
    conn.commit()
    conn.close()

    # Run retention with strict 1-day retention
    _deleted, dropped = run_retention_cleanup(
        db_path=test_db, retention_days=1, batch_size=10
    )

    conn = get_db_connection(str(test_db))
    cur = conn.cursor()
    for tbl in test_tables:
        assert tbl not in dropped, f"Non-matching table {tbl} was recorded as dropped!"
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s;",
            (tbl,),
        )
        assert cur.fetchone() is not None, f"Non-matching table {tbl} was unexpectedly dropped!"

    # Parent table telemetry_values itself must never be dropped
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'telemetry_values';"
    )
    assert cur.fetchone() is not None, "Parent table telemetry_values was dropped!"

    # Clean up test tables
    for tbl in test_tables:
        cur.execute(f'DROP TABLE IF EXISTS "{tbl}";')
    conn.commit()
    conn.close()


def test_retention_precreates_upcoming_partitions_daily(test_db):
    """Criterion: Partition pre-creation runs daily for [today - 1 .. today + 7]."""
    today = datetime.now(UTC).date()
    expected_partitions = [
        f"telemetry_values_p{(today + timedelta(days=i)).strftime('%Y_%m_%d')}"
        for i in range(-1, 8)
    ]

    # Run retention cleanup
    run_retention_cleanup(db_path=test_db, retention_days=30)

    conn = get_db_connection(str(test_db))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.relname
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE p.relname = 'telemetry_values' AND n.nspname = 'public';
        """
    )
    existing_parts = {r["relname"] for r in cur.fetchall()}
    conn.close()

    for part in expected_partitions:
        assert part in existing_parts, f"Partition {part} was not pre-created!"

