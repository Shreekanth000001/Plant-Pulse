"""Optional data migration utility to copy legacy SQLite database data to PostgreSQL.

Uses PostgreSQL COPY for high-throughput bulk streaming.
Ensures daily partitions exist for telemetry_values device_timestamps before COPY.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from db import ensure_partition_for_timestamp, get_database_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("plantpulse.migrate")

BOOLEAN_COLUMNS = {
    "demo_mode",
    "read_only",
    "revoked",
    "is_setpoint",
    "enabled",
    "is_starved",
}

# Ordered topologically to satisfy foreign key constraints
TABLE_ORDER = [
    "plants",
    "plant_tokens",
    "areas",
    "machines",
    "signals",
    "machine_states",
    "alarm_rules",
    "active_alarms",
    "units",
    "stage_events",
    "qc_results",
    "telemetry_values",
]


def _get_sqlite_tables(sqlite_conn: sqlite3.Connection) -> set[str]:
    cur = sqlite_conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    return {row[0] for row in cur.fetchall()}


def _get_sqlite_columns(sqlite_conn: sqlite3.Connection, table_name: str) -> list[str]:
    cur = sqlite_conn.cursor()
    cur.execute(f'PRAGMA table_info("{table_name}");')
    return [row[1] for row in cur.fetchall()]


def _get_postgres_columns(pg_conn: Any, table_name: str) -> list[str]:
    cur = pg_conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position;
        """,
        (table_name,),
    )
    return [row["column_name"] for row in cur.fetchall()]


def precreate_telemetry_partitions(sqlite_conn: sqlite3.Connection, pg_conn: Any) -> int:
    """Pre-create all partitions in Postgres for telemetry_values timestamps in SQLite."""
    cur = sqlite_conn.cursor()
    try:
        cur.execute("SELECT DISTINCT substr(device_timestamp, 1, 10) FROM telemetry_values WHERE device_timestamp IS NOT NULL;")
        dates = [row[0] for row in cur.fetchall() if row[0]]
    except sqlite3.OperationalError:
        return 0

    count = 0
    for d_str in dates:
        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d").replace(tzinfo=UTC)
            ensure_partition_for_timestamp(pg_conn, dt)
            count += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not pre-create partition for date %s: %s", d_str, e)
    return count


def copy_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Any,
    table_name: str,
    batch_size: int = 50000,
) -> int:
    """Stream data from SQLite table into PostgreSQL table via COPY."""
    sqlite_cols = _get_sqlite_columns(sqlite_conn, table_name)
    pg_cols = _get_postgres_columns(pg_conn, table_name)

    # Intersection of columns in SQLite and Postgres, preserving SQLite order
    common_cols = [c for c in sqlite_cols if c in pg_cols]
    if not common_cols:
        logger.info("Table '%s' has no matching columns, skipping.", table_name)
        return 0

    cols_sql = ", ".join(f'"{c}"' for c in common_cols)
    copy_sql = f'COPY "{table_name}" ({cols_sql}) FROM STDIN'

    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute(f'SELECT {cols_sql} FROM "{table_name}";')

    total_rows = 0
    with pg_conn.cursor() as pg_cur, pg_cur.copy(copy_sql) as copy:
        while True:
            rows = sqlite_cur.fetchmany(batch_size)
            if not rows:
                break
            for raw_row in rows:
                # Convert SQLite boolean integer fields to Python booleans
                cleaned_row = []
                for col_name, val in zip(common_cols, raw_row, strict=False):
                    if col_name in BOOLEAN_COLUMNS and val is not None:
                        cleaned_row.append(bool(val))
                    else:
                        cleaned_row.append(val)
                copy.write_row(cleaned_row)
                total_rows += 1

    # Reset serial sequences for tables with autoincrement ID
    if "id" in common_cols:
        with pg_conn.cursor() as cur:
            try:
                cur.execute(
                    f"SELECT pg_get_serial_sequence('{table_name}', 'id') as seq;"
                )
                res = cur.fetchone()
                seq = res["seq"] if res else None
                if seq:
                    cur.execute(
                        f"SELECT setval('{seq}', coalesce(max(id), 1), max(id) IS NOT NULL) FROM \"{table_name}\";"
                    )
            except Exception:  # noqa: BLE001, S110
                pass

    pg_conn.commit()
    logger.info("Migrated table '%s': %d rows.", table_name, total_rows)
    return total_rows


def migrate_sqlite_to_postgres(
    sqlite_path: str | Path,
    postgres_url: str | None = None,
    batch_size: int = 50000,
) -> dict[str, int]:
    """Migrate all recognized PlantPulse tables from SQLite to PostgreSQL."""
    sqlite_file = Path(sqlite_path)
    if not sqlite_file.exists():
        raise FileNotFoundError(f"SQLite database file not found: {sqlite_file}")

    pg_url = postgres_url or get_database_url()
    logger.info("Starting migration from '%s' to '%s'", sqlite_file, pg_url)

    sqlite_conn = sqlite3.connect(str(sqlite_file))
    pg_conn = psycopg.connect(pg_url, row_factory=dict_row)

    results: dict[str, int] = {}
    try:
        sqlite_tables = _get_sqlite_tables(sqlite_conn)

        if "telemetry_values" in sqlite_tables:
            logger.info("Pre-creating PostgreSQL partitions for telemetry_values timestamps...")
            parts = precreate_telemetry_partitions(sqlite_conn, pg_conn)
            logger.info("Pre-created / verified %d daily telemetry partitions.", parts)

        for table in TABLE_ORDER:
            if table in sqlite_tables:
                results[table] = copy_table(
                    sqlite_conn, pg_conn, table, batch_size=batch_size
                )
            else:
                logger.debug("Table '%s' not present in SQLite, skipping.", table)

        logger.info("Migration completed successfully: %s", results)
        return results
    finally:
        sqlite_conn.close()
        pg_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate PlantPulse SQLite database to PostgreSQL via COPY."
    )
    parser.add_argument(
        "--sqlite-path",
        default="platform.db",
        help="Path to source SQLite database (default: platform.db)",
    )
    parser.add_argument(
        "--postgres-url",
        default=None,
        help="Target PostgreSQL connection URL (default: DATABASE_URL env var)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50000,
        help="Batch size for SQLite reads and streaming COPY (default: 50000)",
    )
    args = parser.parse_args()

    try:
        migrate_sqlite_to_postgres(
            sqlite_path=args.sqlite_path,
            postgres_url=args.postgres_url,
            batch_size=args.batch_size,
        )
    except Exception:
        logger.exception("Migration failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
