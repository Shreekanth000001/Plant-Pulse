"""Sync configuration, metadata, credentials, and units from local PostgreSQL to Neon PostgreSQL."""

import json
import os
import psycopg
from psycopg.rows import dict_row

LOCAL_URL = "postgresql://plantpulse:plantpulse@postgres:5432/plantpulse"
NEON_URL = os.getenv("DATABASE_URL_UNPOOLED") or os.getenv("DATABASE_URL")

TABLES = [
    "plants",
    "plant_credentials",
    "plant_members",
    "areas",
    "machines",
    "signals",
    "alarm_rules",
    "units",
    "machine_states",
    "stage_events",
    "qc_results",
]

def sync():
    print(f"Connecting to Local: {LOCAL_URL}")
    local_conn = psycopg.connect(LOCAL_URL, row_factory=dict_row)
    print(f"Connecting to Neon: {NEON_URL[:45]}...")
    neon_conn = psycopg.connect(NEON_URL, row_factory=dict_row)

    for table in TABLES:
        with local_conn.cursor() as l_cur:
            l_cur.execute(f"SELECT * FROM {table};")
            rows = l_cur.fetchall()
            if not rows:
                print(f"Table {table}: 0 rows locally, skipping.")
                continue

            columns = list(rows[0].keys())
            cols_str = ", ".join(columns)
            placeholders = ", ".join(["%s"] * len(columns))

            with neon_conn.cursor() as n_cur:
                count = 0
                for row in rows:
                    vals = []
                    for col in columns:
                        v = row[col]
                        if isinstance(v, (dict, list)):
                            v = json.dumps(v)
                        vals.append(v)

                    if table == "plant_credentials":
                        n_cur.execute(
                            f"""
                            INSERT INTO {table} ({cols_str})
                            VALUES ({placeholders})
                            ON CONFLICT (plant_id, username) DO UPDATE
                            SET client_id = EXCLUDED.client_id,
                                password_hash = EXCLUDED.password_hash,
                                is_active = EXCLUDED.is_active;
                            """,
                            vals
                        )
                    elif table == "plants":
                        n_cur.execute(
                            f"""
                            INSERT INTO {table} ({cols_str})
                            VALUES ({placeholders})
                            ON CONFLICT (id) DO UPDATE
                            SET name = EXCLUDED.name,
                                timezone = EXCLUDED.timezone,
                                viewer_token_hash = EXCLUDED.viewer_token_hash,
                                updated_at = EXCLUDED.updated_at;
                            """,
                            vals
                        )
                    else:
                        n_cur.execute(
                            f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;",
                            vals
                        )
                    count += 1

                neon_conn.commit()
                if table in ["stage_events", "qc_results"]:
                    n_cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1)) FROM {table};")
                    neon_conn.commit()

                print(f"Table {table}: processed {len(rows)} rows (inserted/synced {count}).")

    local_conn.close()
    neon_conn.close()
    print("Sync to Neon completed successfully!")

if __name__ == "__main__":
    sync()
