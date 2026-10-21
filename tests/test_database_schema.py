import sqlite3
from pathlib import Path

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
}

EXPECTED_PKS = {
    "plants": ["id"],
    "plant_credentials": ["plant_id", "username"],
    "areas": ["plant_id", "area_code"],
    "machines": ["plant_id", "machine_code"],
    "signals": ["plant_id", "machine_code", "signal_code"],
    "machine_states": ["plant_id", "machine_code"],
    "telemetry_values": ["id"],
    "alarm_rules": ["id"],
    "active_alarms": ["id"],
    "units": ["plant_id", "unit_id"],
    "stage_events": ["id"],
    "qc_results": ["id"],
}


def get_alembic_config(db_path: Path) -> Config:
    alembic_cfg = Config(str(ALEMBIC_INI))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return alembic_cfg


def run_alembic_upgrade(db_path: Path) -> None:
    command.upgrade(get_alembic_config(db_path), "head")


def test_baseline_migration_runs_on_empty_db(tmp_path):
    """Acceptance criterion: baseline migration runs cleanly on an empty database."""
    db_path = tmp_path / "test_empty.db"
    assert not db_path.exists()

    run_alembic_upgrade(db_path)
    assert db_path.exists()


def test_all_12_tables_exist(tmp_path):
    """Acceptance criterion: all 12 multi-plant tables from Section 3.2 exist."""
    db_path = tmp_path / "test_tables.db"
    run_alembic_upgrade(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert tables >= EXPECTED_TABLES, f"Missing tables: {EXPECTED_TABLES - tables}"


def test_composite_primary_keys_match_design_doc(tmp_path):
    """Acceptance criterion: tables use composite primary keys specified in Section 3.2."""
    db_path = tmp_path / "test_pks.db"
    run_alembic_upgrade(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    for table, expected_pk in EXPECTED_PKS.items():
        cursor.execute(f"PRAGMA table_info({table})")
        pk_cols = [
            row[1]
            for row in sorted(cursor.fetchall(), key=lambda r: r[5])
            if row[5] > 0
        ]
        assert pk_cols == expected_pk, (
            f"Table {table}: expected PK {expected_pk}, got {pk_cols}"
        )

    conn.close()


def test_composite_foreign_keys_match_design_doc(tmp_path):
    """Acceptance criterion: composite foreign keys enforce parent-child relations."""
    db_path = tmp_path / "test_fks.db"
    run_alembic_upgrade(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check machines foreign key to areas (plant_id, area_code)
    cursor.execute("PRAGMA foreign_key_list(machines)")
    fks = cursor.fetchall()
    areas_fk = [fk for fk in fks if fk[2] == "areas"]
    assert len(areas_fk) >= 1, f"Expected FK to areas, got {fks}"

    # Check signals foreign key to machines (plant_id, machine_code)
    cursor.execute("PRAGMA foreign_key_list(signals)")
    fks = cursor.fetchall()
    machines_fk = [fk for fk in fks if fk[2] == "machines"]
    assert len(machines_fk) >= 1, f"Expected FK to machines on signals, got {fks}"

    # Check stage_events foreign keys to units and machines
    cursor.execute("PRAGMA foreign_key_list(stage_events)")
    fks = cursor.fetchall()
    fk_targets = {fk[2] for fk in fks}
    assert "units" in fk_targets, f"stage_events missing FK to units: {fks}"
    assert "machines" in fk_targets, f"stage_events missing FK to machines: {fks}"

    # Check qc_results foreign keys to units and machines
    cursor.execute("PRAGMA foreign_key_list(qc_results)")
    fks = cursor.fetchall()
    fk_targets = {fk[2] for fk in fks}
    assert "units" in fk_targets, f"qc_results missing FK to units: {fks}"
    assert "machines" in fk_targets, f"qc_results missing FK to machines: {fks}"

    conn.close()


def test_foreign_key_violation_enforcement(tmp_path):
    """Acceptance criterion: SQLite foreign key enforcement prevents orphan child rows."""
    db_path = tmp_path / "test_fk_enforce.db"
    run_alembic_upgrade(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")

    # Inserting machine with nonexistent area must fail
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        conn.execute(
            "INSERT INTO machines (plant_id, machine_code, area_code, name) "
            "VALUES ('p1', 'm1', 'nonexistent_area', 'Machine 1')"
        )

    conn.close()


def test_unique_constraints_for_idempotency(tmp_path):
    """Acceptance criterion: unique constraints enforce idempotency as in Section 3.2."""
    db_path = tmp_path / "test_uniques.db"
    run_alembic_upgrade(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")

    # Insert minimal plant, area, machine, signal
    conn.execute("INSERT INTO plants (id, name) VALUES ('p1', 'Plant 1')")
    conn.execute(
        "INSERT INTO areas (plant_id, area_code, name) VALUES ('p1', 'a1', 'Area 1')"
    )
    conn.execute(
        "INSERT INTO machines (plant_id, machine_code, area_code, name) VALUES ('p1', 'm1', 'a1', 'Machine 1')"
    )
    conn.execute(
        "INSERT INTO signals (plant_id, machine_code, signal_code, name) VALUES ('p1', 'm1', 's1', 'Signal 1')"
    )
    conn.commit()

    # Test telemetry_values uniqueness on (plant_id, message_id, signal_code)
    conn.execute(
        "INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, message_id, value_num) "
        "VALUES ('p1', 'm1', 's1', '2026-10-18T00:00:00Z', 'msg_1', 10.5)"
    )
    conn.commit()

    # INSERT OR IGNORE should silently ignore duplicate message_id + signal_code
    conn.execute(
        "INSERT OR IGNORE INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, message_id, value_num) "
        "VALUES ('p1', 'm1', 's1', '2026-10-18T00:00:00Z', 'msg_1', 99.9)"
    )
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[0]
    assert count == 1, f"Expected 1 row after duplicate insert-or-ignore, got {count}"

    conn.close()


def test_migration_downgrade_and_reupgrade(tmp_path):
    """Acceptance criterion: migration can be cleanly rolled back to base and re-applied."""
    db_path = tmp_path / "test_rollback.db"
    alembic_cfg = get_alembic_config(db_path)

    # 1. Upgrade to head
    command.upgrade(alembic_cfg, "head")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables_after_upgrade = {row[0] for row in cursor.fetchall()}
    assert tables_after_upgrade >= EXPECTED_TABLES
    conn.close()

    # 2. Downgrade to base
    command.downgrade(alembic_cfg, "base")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables_after_downgrade = {row[0] for row in cursor.fetchall()}
    assert EXPECTED_TABLES.isdisjoint(tables_after_downgrade)
    conn.close()

    # 3. Re-upgrade to head
    command.upgrade(alembic_cfg, "head")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables_reupgrade = {row[0] for row in cursor.fetchall()}
    assert tables_reupgrade >= EXPECTED_TABLES
    conn.close()


def test_alembic_platform_db_schema_and_db_connection(tmp_path):
    """Acceptance criterion: alembic migration sets up multi-plant schema on platform_db,

    and db.get_db_connection enforces PRAGMA foreign_keys = ON.
    """
    from db import get_db_connection

    platform_db = tmp_path / "platform.db"

    # 1. Run alembic upgrade head against platform_db
    run_alembic_upgrade(platform_db)
    assert platform_db.exists()

    # 2. Check platform_db schema via get_db_connection
    conn_platform = get_db_connection(str(platform_db))
    cur_platform = conn_platform.cursor()
    cur_platform.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    platform_tables = {row[0] for row in cur_platform.fetchall()}
    assert platform_tables >= EXPECTED_TABLES

    # Check that platform 'units' table has plant_id column
    cur_platform.execute("PRAGMA table_info(units)")
    platform_unit_cols = {row[1] for row in cur_platform.fetchall()}
    assert "plant_id" in platform_unit_cols
    assert "unit_id" in platform_unit_cols

    # Check that platform 'stage_events' table has plant_id and machine_code
    cur_platform.execute("PRAGMA table_info(stage_events)")
    platform_stage_cols = {row[1] for row in cur_platform.fetchall()}
    assert "plant_id" in platform_stage_cols
    assert "machine_code" in platform_stage_cols

    # Check that foreign keys pragma is active
    cur_platform.execute("PRAGMA foreign_keys")
    fk_enabled = cur_platform.fetchone()[0]
    assert fk_enabled == 1, "Expected foreign keys to be enabled"

    conn_platform.close()


def test_alembic_default_url_is_platform_db():
    """Acceptance criterion: alembic.ini defaults to sqlite:///./platform.db."""
    alembic_cfg = Config(str(ALEMBIC_INI))
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    assert url == "sqlite:///./platform.db"
