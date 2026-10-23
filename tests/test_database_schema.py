import os
import urllib.parse
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

EXPECTED_TABLES = {
    "plants",
    "plant_credentials",
    "areas",
    "machines",
    "signals",
    "machine_states",
    "telemetry_values",
    "alarm_rules",
    "active_alarms",
    "units",
    "stage_events",
    "qc_results",
    "plant_members",
}

EXPECTED_PKS = {
    "plants": ["id"],
    "plant_credentials": ["plant_id", "username"],
    "areas": ["plant_id", "area_code"],
    "machines": ["plant_id", "machine_code"],
    "signals": ["plant_id", "machine_code", "signal_code"],
    "machine_states": ["plant_id", "machine_code"],
    "telemetry_values": ["device_timestamp", "plant_id", "message_id", "signal_code"],
    "alarm_rules": ["id"],
    "active_alarms": ["id"],
    "units": ["plant_id", "unit_id"],
    "stage_events": ["id"],
    "qc_results": ["id"],
    "plant_members": ["plant_id", "user_id"],
}


def get_alembic_config(db_url: str) -> Config:
    alembic_cfg = Config(str(ALEMBIC_INI))
    if db_url.startswith("postgresql://"):
        sqla_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    else:
        sqla_url = db_url
    alembic_cfg.set_main_option("sqlalchemy.url", sqla_url)
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return alembic_cfg


def run_alembic_upgrade(db_url: str) -> None:
    command.upgrade(get_alembic_config(db_url), "head")


@pytest.fixture
def test_pg_db():
    base_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/plantpulse_test"
    )
    u = urllib.parse.urlparse(base_url)
    maint_url = urllib.parse.urlunparse(u._replace(path="/postgres"))
    target_db = f"plantpulse_schema_test_{uuid.uuid4().hex[:8]}"
    target_url = urllib.parse.urlunparse(u._replace(path=f"/{target_db}"))

    try:
        conn = psycopg.connect(maint_url, autocommit=True)
    except (psycopg.Error, OSError) as e:
        if os.environ.get("CI"):
            pytest.fail(f"PostgreSQL connection required in CI: {e}")
        pytest.skip(f"PostgreSQL not reachable: {e}")

    conn.execute(f"DROP DATABASE IF EXISTS {target_db}")
    conn.execute(f"CREATE DATABASE {target_db}")
    conn.close()

    yield target_url

    try:
        conn = psycopg.connect(maint_url, autocommit=True)
        conn.execute(f"""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = '{target_db}' AND pid <> pg_backend_pid()
        """)
        conn.execute(f"DROP DATABASE IF EXISTS {target_db}")
        conn.close()
    except (psycopg.Error, OSError):
        pass


def test_baseline_migration_runs_on_empty_db(test_pg_db):
    """Acceptance criterion: baseline migration runs cleanly on an empty database."""
    run_alembic_upgrade(test_pg_db)
    with psycopg.connect(test_pg_db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        tables = {row[0] for row in cur.fetchall()}
        assert tables >= EXPECTED_TABLES


def test_all_12_tables_exist(test_pg_db):
    """Acceptance criterion: all 12 multi-plant tables from Section 3.2 exist."""
    run_alembic_upgrade(test_pg_db)
    with psycopg.connect(test_pg_db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        tables = {row[0] for row in cur.fetchall()}
        assert tables >= EXPECTED_TABLES, f"Missing tables: {EXPECTED_TABLES - tables}"


def test_composite_primary_keys_match_design_doc(test_pg_db):
    """Acceptance criterion: tables use composite primary keys specified in Section 3.2."""
    run_alembic_upgrade(test_pg_db)
    with psycopg.connect(test_pg_db) as conn, conn.cursor() as cur:
        for table, expected_pk in EXPECTED_PKS.items():
            cur.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_name = %s
                ORDER BY kcu.ordinal_position
                """,
                (table,),
            )
            pk_cols = [row[0] for row in cur.fetchall()]
            assert pk_cols == expected_pk, (
                f"Table {table}: expected PK {expected_pk}, got {pk_cols}"
            )


def test_composite_foreign_keys_match_design_doc(test_pg_db):
    """Acceptance criterion: composite foreign keys enforce parent-child relations."""
    run_alembic_upgrade(test_pg_db)
    with psycopg.connect(test_pg_db) as conn, conn.cursor() as cur:
        def get_fks(table):
            cur.execute(
                """
                SELECT confrelid::regclass::text AS foreign_table_name
                FROM pg_constraint
                WHERE contype = 'f' AND conrelid = %s::regclass
                """,
                (table,),
            )
            return {row[0] for row in cur.fetchall()}

        machines_fks = get_fks("machines")
        assert "areas" in machines_fks
        assert "plants" in machines_fks

        signals_fks = get_fks("signals")
        assert "machines" in signals_fks

        stage_fks = get_fks("stage_events")
        assert "units" in stage_fks
        assert "machines" in stage_fks

        qc_fks = get_fks("qc_results")
        assert "units" in qc_fks
        assert "machines" in qc_fks

        telemetry_fks = get_fks("telemetry_values")
        assert "machines" in telemetry_fks


def test_foreign_key_violation_enforcement(test_pg_db):
    """Acceptance criterion: PostgreSQL foreign key enforcement prevents orphan child rows."""
    run_alembic_upgrade(test_pg_db)
    with (
        psycopg.connect(test_pg_db) as conn,
        conn.cursor() as cur,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        cur.execute(
                "INSERT INTO machines (plant_id, machine_code, area_code, name) "
                "VALUES ('p1', 'm1', 'nonexistent_area', 'Machine 1')"
            )


def test_unique_constraints_for_idempotency(test_pg_db):
    """Acceptance criterion: unique constraints enforce idempotency as in Section 3.2."""
    from db import ensure_partitions

    run_alembic_upgrade(test_pg_db)
    with psycopg.connect(test_pg_db) as conn:
        ensure_partitions(conn)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO plants (id, name) VALUES ('p1', 'Plant 1')")
            cur.execute(
                "INSERT INTO areas (plant_id, area_code, name) VALUES ('p1', 'a1', 'Area 1')"
            )
            cur.execute(
                "INSERT INTO machines (plant_id, machine_code, area_code, name) "
                "VALUES ('p1', 'm1', 'a1', 'Machine 1')"
            )
            cur.execute(
                "INSERT INTO signals (plant_id, machine_code, signal_code, name) "
                "VALUES ('p1', 'm1', 's1', 'Signal 1')"
            )
            conn.commit()

            now_str = datetime.now(UTC).isoformat()
            cur.execute(
                "INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, message_id, value_num) "
                "VALUES ('p1', 'm1', 's1', %s, 'msg_1', 10.5)",
                (now_str,),
            )
            conn.commit()

            cur.execute(
                "INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, message_id, value_num) "
                "VALUES ('p1', 'm1', 's1', %s, 'msg_1', 99.9) "
                "ON CONFLICT (device_timestamp, plant_id, message_id, signal_code) DO NOTHING",
                (now_str,),
            )
            conn.commit()

            cur.execute("SELECT COUNT(*) FROM telemetry_values")
            count = cur.fetchone()[0]
            assert count == 1, f"Expected 1 row after duplicate insert-or-ignore, got {count}"


def test_migration_downgrade_and_reupgrade(test_pg_db):
    """Acceptance criterion: migration can be cleanly rolled back to base and re-applied."""
    alembic_cfg = get_alembic_config(test_pg_db)

    # 1. Upgrade to head
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(test_pg_db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        tables_after_upgrade = {row[0] for row in cur.fetchall()}
        assert tables_after_upgrade >= EXPECTED_TABLES

    # 2. Downgrade to base
    command.downgrade(alembic_cfg, "base")
    with psycopg.connect(test_pg_db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        tables_after_downgrade = {row[0] for row in cur.fetchall()}
        assert EXPECTED_TABLES.isdisjoint(tables_after_downgrade)

    # 3. Re-upgrade to head
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(test_pg_db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        tables_reupgrade = {row[0] for row in cur.fetchall()}
        assert tables_reupgrade >= EXPECTED_TABLES


def test_alembic_platform_db_schema_and_db_connection(test_pg_db):
    """Acceptance criterion: alembic migration sets up multi-plant schema on PostgreSQL,
    and db.get_db_connection provides working connection.
    """
    from db import get_db_connection

    # 1. Run alembic upgrade head against test_pg_db
    run_alembic_upgrade(test_pg_db)

    # 2. Check schema via get_db_connection
    conn = get_db_connection(test_pg_db)
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    platform_tables = {row["table_name"] for row in cur.fetchall()}
    assert platform_tables >= EXPECTED_TABLES

    # Check that platform 'units' table has plant_id column
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'units'"
    )
    platform_unit_cols = {row["column_name"] for row in cur.fetchall()}
    assert "plant_id" in platform_unit_cols
    assert "unit_id" in platform_unit_cols

    # Check that platform 'stage_events' table has plant_id and machine_code
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'stage_events'"
    )
    platform_stage_cols = {row["column_name"] for row in cur.fetchall()}
    assert "plant_id" in platform_stage_cols
    assert "machine_code" in platform_stage_cols

    conn.close()


def test_alembic_default_url_is_postgres():
    """Acceptance criterion: alembic.ini defaults to postgresql+psycopg URL."""
    alembic_cfg = Config(str(ALEMBIC_INI))
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    assert url.startswith("postgresql+psycopg://")
