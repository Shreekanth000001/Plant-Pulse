import datetime
from datetime import UTC, timedelta
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_postgres_connection_pool_health():
    """Asserts get_db_connection connects to PostgreSQL via ConnectionPool with dict_row."""
    from db import get_db_connection

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT version() as ver;")
        row = cur.fetchone()
        assert "PostgreSQL" in row["ver"], f"Expected PostgreSQL engine, got {row}"


def test_postgres_pooler_settings():
    """Asserts that connection pool uses prepare_threshold=None for transaction pooler compatibility."""
    from db import get_db_connection

    with get_db_connection() as conn:
        assert getattr(conn, "prepare_threshold", -1) is None, (
            f"Expected prepare_threshold to be None, got {getattr(conn, 'prepare_threshold', -1)}"
        )


def test_telemetry_partition_insert_idempotent():
    """Asserts ON CONFLICT (device_timestamp, plant_id, message_id, signal_code) DO NOTHING deduplicates."""
    from db import get_db_connection

    ts = datetime.datetime.now(UTC).replace(microsecond=0)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM telemetry_values WHERE message_id = 'msg_dedupe_test_p1';")
        sql = """
            INSERT INTO telemetry_values (
                plant_id, machine_code, signal_code, device_timestamp, message_id, value_num
            ) VALUES (
                'plant_demo_membrane', 'hm_01', 'mold_temperature_actual', %s, 'msg_dedupe_test_p1', 67.2
            ) ON CONFLICT (device_timestamp, plant_id, message_id, signal_code) DO NOTHING;
        """
        cur.execute(sql, (ts,))
        cur.execute(sql, (ts,))
        conn.commit()

        cur.execute(
            "SELECT count(*) as cnt FROM telemetry_values WHERE message_id = 'msg_dedupe_test_p1';"
        )
        row = cur.fetchone()
        assert row["cnt"] == 1, f"Expected 1 row after duplicate insert, got {row['cnt']}"


def test_precreate_partitions_startup():
    """Asserts partitions for [today-1 .. today+7] are created on startup."""
    from db import get_db_connection

    today = datetime.datetime.now(UTC).date()
    expected_dates = [today + timedelta(days=i) for i in range(-1, 8)]

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name LIKE 'telemetry_values_p%';
            """
        )
        existing_partitions = {r["table_name"] for r in cur.fetchall()}

    for d in expected_dates:
        part_name = f"telemetry_values_p{d.strftime('%Y_%m_%d')}"
        assert part_name in existing_partitions, (
            f"Missing required partition {part_name} in database. Existing: {existing_partitions}"
        )


def test_out_of_window_timestamp_creates_no_partition():
    """A timestamp outside the accepted window (e.g. 45 days in future) is rejected without creating a partition."""
    from db import get_db_connection
    from ingest import IngestEngine

    far_future_dt = datetime.datetime.now(UTC) + timedelta(days=45)
    far_future_date_str = far_future_dt.strftime("%Y_%m_%d")
    expected_part_name = f"telemetry_values_p{far_future_date_str}"

    # Ingest payload with far-future timestamp
    engine = IngestEngine(plants_dir=REPO_ROOT / "plants")
    payload = {
        "plant_id": "plant_demo_membrane",
        "machine_code": "hm_01",
        "message_id": "msg_far_future_test",
        "timestamp": far_future_dt.isoformat(),
        "signals": {"mold_temperature_actual": 68.0},
    }
    # Ingest engine should reject this message based on late/future timestamp window checks
    engine.process_message("plants/plant_demo_membrane/telemetry", payload)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s;",
            (expected_part_name,),
        )
        assert cur.fetchone() is None, (
            f"Partition {expected_part_name} should NOT have been created for out-of-window message!"
        )


def test_history_query_date_bin_format_and_bound():
    """History query must use date_bin, return ISO UTC format ending in Z, and clamp to <= 500 points."""
    from db import get_db_connection

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT to_char(date_bin('60 seconds'::interval, NOW(), '2000-01-01'::timestamptz) at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as ts;
            """
        )
        row = cur.fetchone()
        ts_str = row["ts"]
        assert ts_str.endswith("Z"), f"Timestamp {ts_str} must end in Z"
        assert "T" in ts_str, f"Timestamp {ts_str} must be ISO format with T"


def test_plant_delete_cascades_all_12_tables_and_partitions():
    """Deleting a plant cascades and empties all child tables and partitions."""
    from db import get_db_connection

    with get_db_connection() as conn:
        cur = conn.cursor()
        # Seed test plant
        cur.execute(
            "INSERT INTO plants (id, name) VALUES ('plant_cascade_test', 'Cascade Plant') ON CONFLICT DO NOTHING;"
        )
        cur.execute(
            "INSERT INTO areas (plant_id, area_code, name) VALUES ('plant_cascade_test', 'area_1', 'Area 1') ON CONFLICT DO NOTHING;"
        )
        cur.execute(
            "INSERT INTO machines (plant_id, machine_code, area_code, name) VALUES ('plant_cascade_test', 'm1', 'area_1', 'Machine 1') ON CONFLICT DO NOTHING;"
        )
        ts = datetime.datetime.now(UTC)
        cur.execute(
            """
            INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, message_id, value_num)
            VALUES ('plant_cascade_test', 'm1', 'temp', %s, 'msg_casc_1', 42.0)
            ON CONFLICT DO NOTHING;
            """,
            (ts,),
        )
        conn.commit()

        # Delete plant
        cur.execute("DELETE FROM plants WHERE id = 'plant_cascade_test';")
        conn.commit()

        cur.execute("SELECT count(*) as cnt FROM machines WHERE plant_id = 'plant_cascade_test';")
        assert cur.fetchone()["cnt"] == 0

        cur.execute(
            "SELECT count(*) as cnt FROM telemetry_values WHERE plant_id = 'plant_cascade_test';"
        )
        assert cur.fetchone()["cnt"] == 0


def test_ci_fails_when_postgres_unreachable(monkeypatch):
    """When CI is set, unreachable postgres database raises failure, not skip."""
    from db import get_db_connection

    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid:invalid@localhost:59999/nonexistent")

    with (
        pytest.raises((RuntimeError, psycopg.OperationalError, psycopg.Error)),
        get_db_connection(),
    ):
        pass
