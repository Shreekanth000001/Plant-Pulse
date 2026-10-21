import sqlite3
from datetime import UTC, datetime

import pytest

from db import get_db_connection
from main import init_platform_db
from scripts.migrate_sqlite_to_postgres import migrate_sqlite_to_postgres


@pytest.fixture
def test_sqlite_db(tmp_path):
    sqlite_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(sqlite_path))
    cur = conn.cursor()

    # Create simplified legacy SQLite schema
    cur.execute(
        """
        CREATE TABLE plants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            industry TEXT NOT NULL,
            timezone TEXT NOT NULL,
            currency TEXT NOT NULL,
            demo_mode INTEGER DEFAULT 0,
            read_only INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE areas (
            plant_id TEXT NOT NULL,
            area_code TEXT NOT NULL,
            name TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            PRIMARY KEY (plant_id, area_code)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE machines (
            plant_id TEXT NOT NULL,
            machine_code TEXT NOT NULL,
            area_code TEXT NOT NULL,
            name TEXT NOT NULL,
            machine_type TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            PRIMARY KEY (plant_id, machine_code)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE units (
            plant_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (plant_id, unit_id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE stage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plant_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            machine_code TEXT NOT NULL,
            message_id TEXT NOT NULL,
            is_starved INTEGER DEFAULT 0,
            entered_at TEXT,
            exited_at TEXT,
            outcome TEXT NOT NULL,
            anomaly_score REAL DEFAULT 0.0,
            readings TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE qc_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plant_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            machine_code TEXT NOT NULL,
            message_id TEXT NOT NULL,
            tested_at TEXT NOT NULL,
            outcome TEXT NOT NULL,
            probability REAL NOT NULL,
            defect_type TEXT,
            attributed_stage TEXT
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE telemetry_values (
            plant_id TEXT NOT NULL,
            machine_code TEXT NOT NULL,
            signal_code TEXT NOT NULL,
            device_timestamp TEXT NOT NULL,
            received_at TEXT NOT NULL,
            message_id TEXT NOT NULL,
            value_num REAL,
            value_text TEXT
        );
        """
    )

    now_iso = datetime.now(UTC).isoformat()
    # Insert seed rows
    cur.execute(
        "INSERT INTO plants VALUES ('plant_test_mig', 'Test Plant', 'test', 'mfg', 'UTC', 'USD', 1, 0, ?, ?)",
        (now_iso, now_iso),
    )
    cur.execute(
        "INSERT INTO areas VALUES ('plant_test_mig', 'area_01', 'Area 1', 1)"
    )
    cur.execute(
        "INSERT INTO machines VALUES ('plant_test_mig', 'm_01', 'area_01', 'Machine 1', 'welder', 1)"
    )
    cur.execute(
        "INSERT INTO units VALUES ('plant_test_mig', 'u_mig_01', 'completed', ?, ?)",
        (now_iso, now_iso),
    )
    cur.execute(
        "INSERT INTO stage_events (plant_id, unit_id, machine_code, message_id, is_starved, entered_at, exited_at, outcome, readings) "
        "VALUES ('plant_test_mig', 'u_mig_01', 'm_01', 'msg_stg_mig_1', 0, ?, ?, 'pass', '{}')",
        (now_iso, now_iso),
    )
    cur.execute(
        "INSERT INTO qc_results (plant_id, unit_id, machine_code, message_id, tested_at, outcome, probability) "
        "VALUES ('plant_test_mig', 'u_mig_01', 'm_01', 'msg_qc_mig_1', ?, 'pass', 0.99)",
        (now_iso,),
    )

    # Insert telemetry spanning two different days
    ts1 = "2026-04-10T12:00:00+00:00"
    ts2 = "2026-04-11T14:30:00+00:00"
    cur.execute(
        "INSERT INTO telemetry_values VALUES ('plant_test_mig', 'm_01', 'sig_temp', ?, ?, 'msg_tel_1', 45.2, NULL)",
        (ts1, ts1),
    )
    cur.execute(
        "INSERT INTO telemetry_values VALUES ('plant_test_mig', 'm_01', 'sig_temp', ?, ?, 'msg_tel_2', 46.1, NULL)",
        (ts2, ts2),
    )

    conn.commit()
    conn.close()
    return sqlite_path


def test_migrate_sqlite_to_postgres_copies_data_and_precreates_partitions(
    test_sqlite_db, tmp_path
):
    # Initialize Postgres baseline schema
    dummy_pg_target = tmp_path / "pg.db"
    init_platform_db(dummy_pg_target)

    # Clean any leftover plant_test_mig
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM plants WHERE id = 'plant_test_mig';")

    # Run migration
    results = migrate_sqlite_to_postgres(test_sqlite_db)

    assert results["plants"] == 1
    assert results["areas"] == 1
    assert results["machines"] == 1
    assert results["units"] == 1
    assert results["stage_events"] == 1
    assert results["qc_results"] == 1
    assert results["telemetry_values"] == 2

    # Verify data in PostgreSQL
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM plants WHERE id = 'plant_test_mig';")
        plant = cur.fetchone()
        assert plant is not None
        assert plant["name"] == "Test Plant"
        assert plant["timezone"] == "UTC"

        cur.execute(
            "SELECT COUNT(*) as cnt FROM units WHERE plant_id = 'plant_test_mig';"
        )
        assert cur.fetchone()["cnt"] == 1

        cur.execute(
            "SELECT COUNT(*) as cnt FROM stage_events WHERE plant_id = 'plant_test_mig';"
        )
        assert cur.fetchone()["cnt"] == 1

        cur.execute(
            "SELECT COUNT(*) as cnt FROM qc_results WHERE plant_id = 'plant_test_mig';"
        )
        assert cur.fetchone()["cnt"] == 1

        cur.execute(
            "SELECT COUNT(*) as cnt FROM telemetry_values WHERE plant_id = 'plant_test_mig';"
        )
        assert cur.fetchone()["cnt"] == 2

        # Check that partitions were pre-created
        cur.execute(
            """
            SELECT c.relname
            FROM pg_inherits i
            JOIN pg_class c ON c.oid = i.inhrelid
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'telemetry_values' AND c.relname IN ('telemetry_values_p2026_04_10', 'telemetry_values_p2026_04_11');
            """
        )
        created_parts = {r["relname"] for r in cur.fetchall()}
        assert "telemetry_values_p2026_04_10" in created_parts
        assert "telemetry_values_p2026_04_11" in created_parts

        # Clean up
        cur.execute("DELETE FROM plants WHERE id = 'plant_test_mig';")
