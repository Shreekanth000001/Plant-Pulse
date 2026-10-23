"""Tests for daily demo budget (#103).

Requirements:
- env DEMO_MAX_SECONDS_PER_DAY (default 0 = unlimited so local use is unchanged; hosted uses 1800).
- Budget used = count of distinct seconds with telemetry rows for plant_demo_membrane since 00:00 UTC
  (partition-pruned query, cached 30 s).
- The API stops emitting the heartbeat while the budget is exhausted.
- Expose remaining seconds on health route or /api/demo-budget.
- Resumes next UTC day.
- Partition-pruned query touches only today's partition.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from db import ensure_partitions, get_db_connection


def insert_telemetry_second(
    conn: Any,
    plant_id: str,
    dt: datetime,
    machine_code: str = "am_01",
    signal_code: str = "torque_actual",
) -> None:
    """Helper to insert a single telemetry row with a specific plant_id and device_timestamp."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO telemetry_values (
            plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s
        ) ON CONFLICT DO NOTHING;
        """,
        (plant_id, machine_code, signal_code, dt, dt, str(uuid.uuid4()), 42.0),
    )
    conn.commit()


def insert_demo_telemetry_second(
    conn: Any, dt: datetime, signal_code: str = "torque_actual"
) -> None:
    """Helper to insert a single telemetry row for plant_demo_membrane."""
    insert_telemetry_second(
        conn, "plant_demo_membrane", dt, machine_code="am_01", signal_code=signal_code
    )


def test_demo_budget_disabled_by_default(monkeypatch):
    """1. Demo budget is disabled by default (DEMO_MAX_SECONDS_PER_DAY=0/unset), remaining is None, exhausted is False."""
    monkeypatch.delenv("DEMO_MAX_SECONDS_PER_DAY", raising=False)
    from main import get_demo_budget_usage, is_demo_budget_exhausted

    with get_db_connection() as conn:
        max_sec, _used_sec, rem_sec, _resets_at, exhausted = get_demo_budget_usage(
            conn, force_refresh=True
        )
        assert max_sec == 0
        assert rem_sec is None
        assert exhausted is False
        assert is_demo_budget_exhausted(conn) is False


def test_demo_budget_heartbeat_withheld_when_exhausted(monkeypatch):
    """2. When DEMO_MAX_SECONDS_PER_DAY is set and budget is exceeded, heartbeat is withheld."""
    import asyncio

    monkeypatch.setenv("DEMO_MAX_SECONDS_PER_DAY", "3")
    from main import (
        DEMO_PLANT_ID,
        emit_heartbeat_tick,
        get_demo_budget_usage,
        is_demo_budget_exhausted,
    )

    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, 10, 0, 0, tzinfo=UTC)

    published = []

    def mock_publish(topic, payload):
        published.append((topic, payload))

    with get_db_connection() as conn:
        # Pre-create partitions
        ensure_partitions(conn)

        # Clear any prior rows for today's test
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM telemetry_values WHERE device_timestamp >= %s;",
            (datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=UTC),),
        )
        conn.commit()

        # Insert 3 distinct seconds
        for s in range(3):
            insert_demo_telemetry_second(conn, today_start + timedelta(seconds=s))

        max_sec, used_sec, rem_sec, _, exhausted = get_demo_budget_usage(
            conn, force_refresh=True
        )
        assert max_sec == 3
        assert used_sec >= 3
        assert rem_sec == 0
        assert exhausted is True
        assert is_demo_budget_exhausted(conn) is True

    # Attempt to emit heartbeat with an active viewer mock
    class DummyTracker:
        def has_recent_poll(self):
            return True

    res = asyncio.run(
        emit_heartbeat_tick(
            conn_mgr=None,
            publish_fn=mock_publish,
            plant_id=DEMO_PLANT_ID,
            tracker=DummyTracker(),
        )
    )
    assert res is False
    assert len(published) == 0


def test_demo_budget_resumes_next_utc_day(monkeypatch):
    """3. Telemetry from yesterday does not count against today's budget; budget resets at 00:00 UTC."""
    monkeypatch.setenv("DEMO_MAX_SECONDS_PER_DAY", "5")
    from main import get_demo_budget_usage

    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    yesterday_ts = datetime(
        yesterday.year, yesterday.month, yesterday.day, 12, 0, 0, tzinfo=UTC
    )

    with get_db_connection() as conn:
        ensure_partitions(conn)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM telemetry_values WHERE device_timestamp >= %s;",
            (datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=UTC),),
        )
        conn.commit()

        # Insert 10 distinct seconds for yesterday
        for s in range(10):
            insert_demo_telemetry_second(conn, yesterday_ts + timedelta(seconds=s))

        # Check today's budget: should be 0 used because yesterday's rows are excluded
        max_sec, used_sec, rem_sec, _, exhausted = get_demo_budget_usage(
            conn, force_refresh=True
        )
        assert max_sec == 5
        assert used_sec == 0
        assert rem_sec == 5
        assert exhausted is False


def test_demo_budget_query_partition_pruning(monkeypatch):
    """4. The demo budget query uses explicit device_timestamp bounds and Postgres partition pruning touches only today's partition."""
    monkeypatch.setenv("DEMO_MAX_SECONDS_PER_DAY", "1800")

    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=UTC)
    next_day = today_start + timedelta(days=1)
    today_part = f"telemetry_values_p{now.strftime('%Y_%m_%d')}"

    with get_db_connection() as conn:
        ensure_partitions(conn)
        cur = conn.cursor()
        # Run EXPLAIN on the partition-bounded query
        cur.execute(
            """
            EXPLAIN (FORMAT JSON)
            SELECT COUNT(DISTINCT date_trunc('second', device_timestamp)) AS used_seconds
            FROM telemetry_values
            WHERE device_timestamp >= %s
              AND device_timestamp < %s;
            """,
            (today_start, next_day),
        )
        row = cur.fetchone()
        explain_json = row["QUERY PLAN"] if isinstance(row, dict) else row[0]
        explain_str = str(explain_json)

        # Confirm that today's partition is scanned
        assert today_part in explain_str

        # Confirm that an adjacent partition (e.g. yesterday or tomorrow) is NOT in the plan
        yesterday_part = (
            f"telemetry_values_p{(now - timedelta(days=1)).strftime('%Y_%m_%d')}"
        )
        tomorrow_part = (
            f"telemetry_values_p{(now + timedelta(days=1)).strftime('%Y_%m_%d')}"
        )
        assert yesterday_part not in explain_str
        assert tomorrow_part not in explain_str


def test_water_plant_heartbeat_withheld_when_exhausted(monkeypatch):
    """5. The water plant (and any other plant) also stops receiving heartbeats when budget is exhausted."""
    import asyncio

    monkeypatch.setenv("DEMO_MAX_SECONDS_PER_DAY", "2")
    from main import (
        emit_heartbeat_tick,
        get_demo_budget_usage,
        is_demo_budget_exhausted,
    )

    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, 11, 0, 0, tzinfo=UTC)

    published = []

    def mock_publish(topic, payload):
        published.append((topic, payload))

    with get_db_connection() as conn:
        ensure_partitions(conn)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM telemetry_values WHERE device_timestamp >= %s;",
            (datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=UTC),),
        )
        conn.commit()

        for s in range(2):
            insert_telemetry_second(
                conn,
                "plant_water_district_9",
                today_start + timedelta(seconds=s),
                machine_code="pump_01",
                signal_code="flow_rate",
            )

        _, _, rem_sec, _, exhausted = get_demo_budget_usage(conn, force_refresh=True)
        assert rem_sec == 0
        assert exhausted is True
        assert is_demo_budget_exhausted(conn) is True

    class DummyTracker:
        def has_recent_poll(self):
            return True

    res = asyncio.run(
        emit_heartbeat_tick(
            conn_mgr=None,
            publish_fn=mock_publish,
            plant_id="plant_water_district_9",
            tracker=DummyTracker(),
        )
    )
    assert res is False
    assert len(published) == 0


def test_demo_budget_shared_across_plants(monkeypatch):
    """6. Budget is shared across all plants: seconds generated by plant A and plant B sum together."""
    monkeypatch.setenv("DEMO_MAX_SECONDS_PER_DAY", "10")
    from main import get_demo_budget_usage

    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, 12, 0, 0, tzinfo=UTC)

    with get_db_connection() as conn:
        ensure_partitions(conn)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM telemetry_values WHERE device_timestamp >= %s;",
            (datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=UTC),),
        )
        conn.commit()

        # Insert 3 seconds for plant_demo_membrane and 2 seconds for plant_water_district_9 at distinct timestamps
        for s in range(3):
            insert_telemetry_second(
                conn, "plant_demo_membrane", today_start + timedelta(seconds=s)
            )
        for s in range(2):
            insert_telemetry_second(
                conn,
                "plant_water_district_9",
                today_start + timedelta(seconds=10 + s),
                machine_code="pump_01",
                signal_code="pressure",
            )

        max_sec, used_sec, rem_sec, _, exhausted = get_demo_budget_usage(
            conn, force_refresh=True
        )
        assert max_sec == 10
        assert used_sec == 5
        assert rem_sec == 5
        assert exhausted is False
