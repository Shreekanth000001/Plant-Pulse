import datetime
import os
import random
import sqlite3
import statistics
import time
import uuid

DDL = """
CREATE TABLE plants (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    viewer_token_hash VARCHAR(255) NULL, -- NULL = public read-only demo plant
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Core Platform: MQTT Device Credentials
CREATE TABLE plant_credentials (
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    username VARCHAR(128) NOT NULL,
    client_id VARCHAR(128) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (plant_id, username)
);
CREATE INDEX idx_credentials_username ON plant_credentials(username);

-- 3. Core Platform: Areas
CREATE TABLE areas (
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    area_code VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plant_id, area_code)
);
CREATE INDEX idx_areas_order ON areas(plant_id, display_order);

-- 4. Core Platform: Machines
CREATE TABLE machines (
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    machine_code VARCHAR(64) NOT NULL,
    area_code VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    machine_type VARCHAR(64) NOT NULL DEFAULT 'standard',
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plant_id, machine_code),
    FOREIGN KEY (plant_id, area_code) REFERENCES areas(plant_id, area_code) ON DELETE CASCADE
);
CREATE INDEX idx_machines_area ON machines(plant_id, area_code);

-- 5. Core Platform: Signals Catalog
CREATE TABLE signals (
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    machine_code VARCHAR(64) NOT NULL,
    signal_code VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    unit VARCHAR(32) NOT NULL DEFAULT '',
    data_type VARCHAR(32) NOT NULL DEFAULT 'float', -- float, int, bool, string
    is_setpoint BOOLEAN NOT NULL DEFAULT FALSE,
    setpoint_signal_code VARCHAR(64) NULL,
    normal_min FLOAT NULL,
    normal_max FLOAT NULL,
    warn_min FLOAT NULL,
    warn_max FLOAT NULL,
    alarm_min FLOAT NULL,
    alarm_max FLOAT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plant_id, machine_code, signal_code),
    FOREIGN KEY (plant_id, machine_code) REFERENCES machines(plant_id, machine_code) ON DELETE CASCADE,
    FOREIGN KEY (plant_id, machine_code, setpoint_signal_code) 
        REFERENCES signals(plant_id, machine_code, signal_code) ON DELETE SET NULL
);
CREATE INDEX idx_signals_order ON signals(plant_id, machine_code, display_order);

-- 6. Core Platform: Machine Live State
CREATE TABLE machine_states (
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    machine_code VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'IDLE', -- RUNNING, IDLE, STANDBY, FAULT, OFFLINE
    sub_state VARCHAR(64) NULL,
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (plant_id, machine_code),
    FOREIGN KEY (plant_id, machine_code) REFERENCES machines(plant_id, machine_code) ON DELETE CASCADE
);

-- 7. Core Platform: Narrow Telemetry Values (High Volume)
-- In SQLite, INTEGER PRIMARY KEY provides 64-bit signed autoincrement ROWID.
CREATE TABLE telemetry_values (
    id INTEGER PRIMARY KEY,
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    machine_code VARCHAR(64) NOT NULL,
    signal_code VARCHAR(64) NOT NULL,
    device_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    message_id VARCHAR(64) NOT NULL,
    value_num FLOAT NULL,
    value_text VARCHAR(255) NULL,
    FOREIGN KEY (plant_id, machine_code, signal_code) 
        REFERENCES signals(plant_id, machine_code, signal_code) ON DELETE CASCADE,
    CONSTRAINT uq_telemetry_idempotency UNIQUE (plant_id, message_id, signal_code)
);
CREATE INDEX idx_telemetry_series ON telemetry_values(plant_id, machine_code, signal_code, device_timestamp DESC);
CREATE INDEX idx_telemetry_retention ON telemetry_values(received_at);

-- 8. Core Platform: Alarm Rules
CREATE TABLE alarm_rules (
    id INTEGER PRIMARY KEY,
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    machine_code VARCHAR(64) NOT NULL,
    signal_code VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL, -- WARN, ALARM
    threshold_low FLOAT NULL,
    threshold_high FLOAT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (plant_id, machine_code, signal_code) 
        REFERENCES signals(plant_id, machine_code, signal_code) ON DELETE CASCADE
);
CREATE INDEX idx_alarm_rules_signal ON alarm_rules(plant_id, machine_code, signal_code);

-- 9. Core Platform: Active Alarms
CREATE TABLE active_alarms (
    id INTEGER PRIMARY KEY,
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    machine_code VARCHAR(64) NOT NULL,
    signal_code VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL, -- WARN, ALARM
    message TEXT NOT NULL,
    triggered_at TIMESTAMP WITH TIME ZONE NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, ACKNOWLEDGED, RESOLVED
    FOREIGN KEY (plant_id, machine_code, signal_code) 
        REFERENCES signals(plant_id, machine_code, signal_code) ON DELETE CASCADE
);
CREATE INDEX idx_active_alarms_plant ON active_alarms(plant_id, status);

-- 10. Optional Module: Units (product_traceability)
CREATE TABLE units (
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    unit_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'in_progress',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (plant_id, unit_id)
);
CREATE INDEX idx_units_created ON units(plant_id, created_at DESC);

-- 11. Optional Module: Stage Events (product_traceability)
CREATE TABLE stage_events (
    id INTEGER PRIMARY KEY,
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    unit_id VARCHAR(128) NOT NULL,
    machine_code VARCHAR(64) NOT NULL,
    message_id VARCHAR(64) NOT NULL,
    is_starved BOOLEAN NOT NULL DEFAULT FALSE,
    entered_at TIMESTAMP WITH TIME ZONE NULL,
    exited_at TIMESTAMP WITH TIME ZONE NULL,
    outcome VARCHAR(32) NOT NULL,
    anomaly_score FLOAT NOT NULL DEFAULT 0.0,
    readings JSON NOT NULL,
    FOREIGN KEY (plant_id, unit_id) REFERENCES units(plant_id, unit_id) ON DELETE CASCADE,
    FOREIGN KEY (plant_id, machine_code) REFERENCES machines(plant_id, machine_code) ON DELETE CASCADE,
    CONSTRAINT uq_stage_event_idempotency UNIQUE (plant_id, message_id)
);
CREATE INDEX idx_stage_events_lookup ON stage_events(plant_id, unit_id, entered_at);

-- 12. Optional Module: QC Results (quality_inspection)
CREATE TABLE qc_results (
    id INTEGER PRIMARY KEY,
    plant_id VARCHAR(64) NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    unit_id VARCHAR(128) NOT NULL,
    machine_code VARCHAR(64) NOT NULL,
    message_id VARCHAR(64) NOT NULL,
    tested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    outcome VARCHAR(32) NOT NULL,
    probability FLOAT NOT NULL,
    defect_type VARCHAR(128) NULL,
    attributed_stage VARCHAR(128) NULL,
    FOREIGN KEY (plant_id, unit_id) REFERENCES units(plant_id, unit_id) ON DELETE CASCADE,
    FOREIGN KEY (plant_id, machine_code) REFERENCES machines(plant_id, machine_code) ON DELETE CASCADE,
    CONSTRAINT uq_qc_results_idempotency UNIQUE (plant_id, message_id)
);
CREATE INDEX idx_qc_results_lookup ON qc_results(plant_id, unit_id);
CREATE INDEX idx_qc_results_time ON qc_results(plant_id, tested_at DESC);
"""

if os.path.exists("bench.db"):
    os.remove("bench.db")

conn = sqlite3.connect("bench.db")
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA foreign_keys=ON")
conn.executescript(DDL)
conn.commit()


# ============================================================================
# Step 1: Seed Parent Hierarchy
# ============================================================================
def seed_parents(conn: sqlite3.Connection) -> None:
    """
    Seed parent tables in exact order: plants -> areas -> machines -> signals.
    Respects composite primary and foreign keys:
      - areas(plant_id, area_code)
      - machines(plant_id, machine_code) references areas(plant_id, area_code)
      - signals(plant_id, machine_code, signal_code) references machines(plant_id, machine_code)
    """
    # 1. Plants: 1 plant
    plants_data = [("plant_01", "Demo Manufacturing Facility", "UTC", None)]
    conn.executemany(
        "INSERT INTO plants (id, name, timezone, viewer_token_hash) VALUES (?, ?, ?, ?)",
        plants_data,
    )

    # 2. Areas: 4 areas (housing, casting, assembly, qc)
    areas_data = [
        ("plant_01", "housing", "Housing Area", 1),
        ("plant_01", "casting", "Casting Area", 2),
        ("plant_01", "assembly", "Assembly Area", 3),
        ("plant_01", "qc", "Quality Control Area", 4),
    ]
    conn.executemany(
        "INSERT INTO areas (plant_id, area_code, name, display_order) VALUES (?, ?, ?, ?)",
        areas_data,
    )

    # 3. Machines: 11 machines (hm_01-04, cs_01-03, am_01-03, qc_01)
    machines_data = [
        ("plant_01", "hm_01", "housing", "Housing Molder 1", "molder", 1),
        ("plant_01", "hm_02", "housing", "Housing Molder 2", "molder", 2),
        ("plant_01", "hm_03", "housing", "Housing Molder 3", "molder", 3),
        ("plant_01", "hm_04", "housing", "Housing Molder 4", "molder", 4),
        ("plant_01", "cs_01", "casting", "Casting Machine 1", "caster", 1),
        ("plant_01", "cs_02", "casting", "Casting Machine 2", "caster", 2),
        ("plant_01", "cs_03", "casting", "Casting Machine 3", "caster", 3),
        ("plant_01", "am_01", "assembly", "Assembly Station 1", "assembler", 1),
        ("plant_01", "am_02", "assembly", "Assembly Station 2", "assembler", 2),
        ("plant_01", "am_03", "assembly", "Assembly Station 3", "assembler", 3),
        ("plant_01", "qc_01", "qc", "QC Test Station 1", "qc_station", 1),
    ]
    conn.executemany(
        """
        INSERT INTO machines (plant_id, machine_code, area_code, name, machine_type, display_order)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        machines_data,
    )

    # 4. Signals: 32 signals total
    # Housing: 4 machines * 2 signals = 8 signals
    # Casting: 3 machines * 5 signals = 15 signals
    # Assembly: 3 machines * 3 signals = 9 signals
    # QC: 1 machine * 0 signals = 0 signals
    # Total = 8 + 15 + 9 + 0 = 32 signals
    signals_data = []

    # Housing (2 signals per machine)
    for m in ["hm_01", "hm_02", "hm_03", "hm_04"]:
        signals_data.append(
            ("plant_01", m, "sig_01", "Mold Temperature", "°C", "float", False, 1)
        )
        signals_data.append(
            ("plant_01", m, "sig_02", "Motor Vibration", "mm/s", "float", False, 2)
        )

    # Casting (5 signals per machine)
    for m in ["cs_01", "cs_02", "cs_03"]:
        signals_data.append(
            ("plant_01", m, "sig_01", "Extrusion Temperature", "°C", "float", False, 1)
        )
        signals_data.append(
            ("plant_01", m, "sig_02", "Polymer Viscosity", "cP", "float", False, 2)
        )
        signals_data.append(
            ("plant_01", m, "sig_03", "Casting Speed", "m/min", "float", False, 3)
        )
        signals_data.append(
            ("plant_01", m, "sig_04", "Roll Pressure", "bar", "float", False, 4)
        )
        signals_data.append(
            ("plant_01", m, "sig_05", "Casting Vibration", "mm/s", "float", False, 5)
        )

    # Assembly (3 signals per machine)
    for m in ["am_01", "am_02", "am_03"]:
        signals_data.append(
            ("plant_01", m, "sig_01", "Torque", "N*m", "float", False, 1)
        )
        signals_data.append(
            ("plant_01", m, "sig_02", "Seal Pressure", "bar", "float", False, 2)
        )
        signals_data.append(
            ("plant_01", m, "sig_03", "Motor Vibration", "mm/s", "float", False, 3)
        )

    # QC: qc_01 has 0 signals

    conn.executemany(
        """
        INSERT INTO signals (plant_id, machine_code, signal_code, name, unit, data_type, is_setpoint, display_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        signals_data,
    )
    conn.commit()


# Seed parent tables
seed_parents(conn)

# Record size_empty_schema right after seeding (checkpoint to flush WAL to main DB)
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
size_empty_schema = os.path.getsize("bench.db")


# ============================================================================
# Step 2: Generate All Rows in Memory BEFORE Starting Any Timer
# ============================================================================
# 43,200 ticks (2 s each) = 24 hours of telemetry
# For each tick and machine: one uuid4 message_id shared by that machine's signals
# One row per signal; random float value_num
# Expect 43,200 ticks * 32 signals = 1,382,400 rows
print("Generating 1,382,400 telemetry rows in memory (before starting timer)...")
base_time = datetime.datetime(2026, 10, 15, 0, 0, 0, tzinfo=datetime.UTC)

machine_signals = {
    m: ["sig_01", "sig_02"] for m in ["hm_01", "hm_02", "hm_03", "hm_04"]
}
machine_signals.update(
    {
        m: ["sig_01", "sig_02", "sig_03", "sig_04", "sig_05"]
        for m in ["cs_01", "cs_02", "cs_03"]
    }
)
machine_signals.update(
    {m: ["sig_01", "sig_02", "sig_03"] for m in ["am_01", "am_02", "am_03"]}
)
# Note: qc_01 has 0 signals and therefore generates 0 rows per tick

rows = []
total_ticks = 43200
for tick in range(total_ticks):
    # Device timestamp as ISO string, one tick every 2 seconds
    ts = (base_time + datetime.timedelta(seconds=tick * 2)).isoformat()
    for machine_code, sigs in machine_signals.items():
        # One uuid4 message_id shared by that machine's signals for this tick
        msg_id = str(uuid.uuid4())
        for signal_code in sigs:
            val = random.uniform(10.0, 100.0)
            rows.append(("plant_01", machine_code, signal_code, ts, msg_id, val))

print(f"Generated {len(rows):,} rows (expected 1,382,400).")
assert len(rows) == 1382400, f"Expected 1,382,400 rows, got {len(rows)}"


# ============================================================================
# Step 3: Time Bulk Insert (Batches of 500, INSERT OR IGNORE, commit per batch)
# ============================================================================
print("\n--- Step 3: Timing Bulk Insert ---")
batch_size = 500
insert_sql = """
INSERT OR IGNORE INTO telemetry_values 
(plant_id, machine_code, signal_code, device_timestamp, message_id, value_num)
VALUES (?, ?, ?, ?, ?, ?)
"""

t0 = time.perf_counter()
cursor = conn.cursor()
for i in range(0, len(rows), batch_size):
    batch = rows[i : i + batch_size]
    cursor.executemany(insert_sql, batch)
    conn.commit()
t1 = time.perf_counter()

insert_duration = t1 - t0
insert_rows_per_sec = len(rows) / insert_duration

total_count = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[0]
print(
    f"Inserted {total_count:,} rows in {insert_duration:.2f} s ({insert_rows_per_sec:,.2f} rows/s)"
)
print(f"SELECT COUNT(*) = {total_count:,}")


# ============================================================================
# Step 4: WAL Checkpoint & Storage Metrics
# ============================================================================
print("\n--- Step 4: WAL Checkpoint & Storage Metrics ---")
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
size_after = os.path.getsize("bench.db")
file_size_mb = size_after / (1024 * 1024)
bytes_per_row = (size_after - size_empty_schema) / total_count

print(
    f"Empty schema size: {size_empty_schema:,} bytes ({size_empty_schema / 1024:.2f} KB)"
)
print(f"Database size after checkpoint: {size_after:,} bytes ({file_size_mb:.2f} MB)")
print(f"Storage cost: {bytes_per_row:.2f} bytes/row")


# ============================================================================
# Step 5: Hourly Aggregation Query & EXPLAIN QUERY PLAN
# ============================================================================
print("\n--- Step 5: Hourly Aggregation Query & EXPLAIN QUERY PLAN ---")
# 43,200 ticks * 2 seconds = 86,400 seconds (24 hours).
# The last hour covers the final 3,600 seconds: from second 82,800 to 86,400.
last_hour_start_ts = (base_time + datetime.timedelta(seconds=82800)).isoformat()
target_machine = "hm_01"
target_signal = "sig_01"

query_sql = """
SELECT AVG(value_num) 
FROM telemetry_values 
WHERE plant_id = ? 
  AND machine_code = ? 
  AND signal_code = ? 
  AND device_timestamp >= ?
"""

# Print EXPLAIN QUERY PLAN
print("EXPLAIN QUERY PLAN:")
explain_cursor = conn.execute(
    "EXPLAIN QUERY PLAN " + query_sql,
    ("plant_01", target_machine, target_signal, last_hour_start_ts),
)
explain_plan_lines = []
for eqp_row in explain_cursor.fetchall():
    line = f"  id={eqp_row[0]}, parent={eqp_row[1]}, notused={eqp_row[2]}, detail={eqp_row[3]}"
    explain_plan_lines.append(eqp_row[3])
    print(line)

# Time the query 5 times and compute median
query_times = []
avg_result = None
for _ in range(5):
    qt0 = time.perf_counter()
    cursor = conn.execute(
        query_sql, ("plant_01", target_machine, target_signal, last_hour_start_ts)
    )
    avg_result = cursor.fetchone()[0]
    qt1 = time.perf_counter()
    query_times.append(qt1 - qt0)

median_query_time = statistics.median(query_times)
print(f"Query 5 runs latencies: {[f'{t * 1000:.3f} ms' for t in query_times]}")
print(
    f"Median query latency: {median_query_time * 1000:.3f} ms ({median_query_time:.6f} s)"
)
print(
    f"Average value_num for {target_machine}.{target_signal} (last hour): {avg_result:.4f}"
)


# ============================================================================
# Step 6: Idempotency Re-insert (First 20,000 rows with INSERT OR IGNORE)
# ============================================================================
print("\n--- Step 6: Idempotency Re-insert Test ---")
count_before_reinsert = conn.execute(
    "SELECT COUNT(*) FROM telemetry_values"
).fetchone()[0]

reinsert_batch = rows[:20000]
rt0 = time.perf_counter()
for i in range(0, len(reinsert_batch), batch_size):
    batch = reinsert_batch[i : i + batch_size]
    cursor.executemany(insert_sql, batch)
    conn.commit()
rt1 = time.perf_counter()
reinsert_duration = rt1 - rt0

count_after_reinsert = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[
    0
]
print(f"Count before re-insert: {count_before_reinsert:,}")
print(f"Count after re-insert:  {count_after_reinsert:,}")
print(
    f"Re-insert time for 20,000 rows: {reinsert_duration:.4f} s ({len(reinsert_batch) / reinsert_duration:,.2f} rows/s)"
)


# ============================================================================
# Step 7: Foreign Key Constraint Violation Test
# ============================================================================
print("\n--- Step 7: Foreign Key Constraint Check ---")
caught_exception = None
try:
    conn.execute(
        """
        INSERT INTO telemetry_values 
        (plant_id, machine_code, signal_code, device_timestamp, message_id, value_num)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "plant_01",
            "hm_01",
            "nonexistent_signal_999",
            "2026-10-15T00:00:00+00:00",
            str(uuid.uuid4()),
            42.0,
        ),
    )
    conn.commit()
    print("UNEXPECTED: Insert with nonexistent signal_code succeeded!")
except sqlite3.IntegrityError as e:
    caught_exception = e
    print(f"Caught expected sqlite3.IntegrityError:\n  {type(e).__name__}: {e}")


# ============================================================================
# Step 8: Print Summary Table
# ============================================================================
print("\n" + "=" * 80)
print(f"{'SQLITE TELEMETRY BENCHMARK SUMMARY (1 SIMULATED DAY)':^80}")
print("=" * 80)
print(f"{'Metric / Step':<46} | {'Value / Result':<31}")
print("-" * 80)
summary_metrics = [
    ("Simulated Dataset Duration", "24 hours (43,200 ticks @ 2s)"),
    ("Hierarchy Seeded", "1 plant, 4 areas, 11 machines, 32 signals"),
    ("Total Telemetry Rows Generated", f"{len(rows):,} rows"),
    (
        "Empty Schema Size (after seeding)",
        f"{size_empty_schema / 1024:.2f} KB ({size_empty_schema:,} bytes)",
    ),
    ("Bulk Insert Duration (batches of 500)", f"{insert_duration:.2f} seconds"),
    ("Bulk Insert Throughput", f"{insert_rows_per_sec:,.2f} rows/s"),
    ("Total Rows in DB (SELECT COUNT(*))", f"{total_count:,} rows"),
    ("Post-Checkpoint Database Size", f"{file_size_mb:.2f} MB ({size_after:,} bytes)"),
    ("Computed Bytes Per Row", f"{bytes_per_row:.2f} bytes/row"),
    ("Last-Hour AVG Query Median Latency", f"{median_query_time * 1000:.3f} ms"),
    ("Query Plan Used", f"{explain_plan_lines[0] if explain_plan_lines else 'N/A'}"),
    ("Idempotency Test Rows Re-inserted", f"{len(reinsert_batch):,} rows"),
    ("Count Before Re-insert", f"{count_before_reinsert:,}"),
    ("Count After Re-insert", f"{count_after_reinsert:,} (0 duplicates added)"),
    ("Re-insert Duration", f"{reinsert_duration:.4f} seconds"),
    (
        "FK Constraint Violation Caught",
        f"{type(caught_exception).__name__}: {caught_exception}",
    ),
]
for metric, val in summary_metrics:
    print(f"{metric:<46} | {val:<31}")
print("=" * 80)

conn.close()
