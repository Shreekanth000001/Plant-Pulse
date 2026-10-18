import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from ingest import IngestEngine, sync_plant_definitions
from plant_definitions import load_plants

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
    db_path = tmp_path / "test_platform.db"
    run_alembic_upgrade(db_path)

    # Seed parents from plants/*.json
    plants = load_plants(PLANTS_DIR)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    sync_plant_definitions(conn, plants)
    conn.close()

    return db_path


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
async def test_duplicate_messages_are_ignored(test_db):
    """Acceptance criterion: duplicate deliveries (same message_id, signal_code) are ignored via UNIQUE constraint + insert-or-ignore."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(test_db, plants=plants, batch_size=100)

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
    payload1 = make_valid_payload(message_id="msg-dup-123")
    payload2 = make_valid_payload(message_id="msg-dup-123")

    accepted1 = await engine.enqueue(topic, payload1)
    accepted2 = await engine.enqueue(topic, payload2)
    assert accepted1 is True
    assert accepted2 is True

    await engine.flush()

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM telemetry_values")
    count = cursor.fetchone()[0]
    conn.close()

    # Payload has 3 metrics -> exactly 3 rows, not 6
    assert count == 3


@pytest.mark.anyio
async def test_readings_more_than_5_minutes_in_future_rejected(test_db):
    """Acceptance criterion: readings timestamped > 5 minutes in future are rejected."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(test_db, plants=plants)

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
    future_time = datetime.now(UTC) + timedelta(minutes=10)
    payload = make_valid_payload(timestamp=future_time)

    accepted = await engine.enqueue(topic, payload)
    assert accepted is False

    await engine.flush()

    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[0]
    conn.close()
    assert count == 0


@pytest.mark.anyio
async def test_late_readings_within_configured_window_accepted(test_db):
    """Acceptance criterion: late data within MAX_LATE_SECONDS (e.g. 2 hours old) is accepted and indexed by device_timestamp."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(test_db, plants=plants, max_late_seconds=21600)

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
    past_time = datetime.now(UTC) - timedelta(hours=2)
    payload = make_valid_payload(message_id="msg-late-valid", timestamp=past_time)

    accepted = await engine.enqueue(topic, payload)
    assert accepted is True

    await engine.flush()

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT device_timestamp FROM telemetry_values WHERE message_id = 'msg-late-valid'"
    )
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 3
    # Device timestamp matches the past time
    assert rows[0][0].startswith(past_time.strftime("%Y-%m-%d"))


@pytest.mark.anyio
async def test_late_readings_older_than_window_rejected(test_db):
    """Acceptance criterion: readings older than MAX_LATE_SECONDS (e.g. 7 hours old with 6h window) are rejected."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(test_db, plants=plants, max_late_seconds=21600)

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
    too_old_time = datetime.now(UTC) - timedelta(hours=7)
    payload = make_valid_payload(message_id="msg-too-old", timestamp=too_old_time)

    accepted = await engine.enqueue(topic, payload)
    assert accepted is False

    await engine.flush()

    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[0]
    conn.close()
    assert count == 0


@pytest.mark.anyio
async def test_bounded_queue_and_drop_counter(test_db):
    """Acceptance criterion: queue is bounded; drops are counted in ingest_dropped_total when full."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(test_db, plants=plants, max_queue_size=5)

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"

    # Enqueue 10 messages without consumer running
    accepted_count = 0
    rejected_count = 0
    for i in range(10):
        payload = make_valid_payload(message_id=f"msg-drop-{i}")
        if await engine.enqueue(topic, payload):
            accepted_count += 1
        else:
            rejected_count += 1

    assert accepted_count == 5
    assert rejected_count == 5
    assert engine.dropped_total == 5


@pytest.mark.anyio
async def test_batches_commit_on_100_items(test_db):
    """Acceptance criterion: batches commit immediately when 100 items are queued without waiting 500 ms."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(
        test_db,
        plants=plants,
        batch_size=100,
        flush_interval_seconds=60.0,  # Long timer to prove commit is triggered by count
    )
    await engine.start()

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
    # Each message has 2 signals -> 50 messages = 100 items
    metrics = {"mold_temperature_actual": 65.0, "vibration_mms": 1.5}
    for i in range(50):
        await engine.enqueue(
            topic, make_valid_payload(message_id=f"msg-batch-{i}", metrics=metrics)
        )

    # Give consumer worker a moment to process the 100 items
    for _ in range(20):
        await asyncio.sleep(0.05)
        conn = sqlite3.connect(test_db)
        count = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[0]
        conn.close()
        if count >= 100:
            break

    await engine.stop()

    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[0]
    conn.close()
    assert count == 100


@pytest.mark.anyio
async def test_batches_commit_on_500ms_timer(test_db):
    """Acceptance criterion: batches commit on 500 ms timer even when items < batch_size."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(
        test_db,
        plants=plants,
        batch_size=100,
        flush_interval_seconds=0.5,
    )
    await engine.start()

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
    # 1 message has 2 signals (< 100 items)
    metrics = {"mold_temperature_actual": 65.0, "vibration_mms": 1.5}
    await engine.enqueue(
        topic, make_valid_payload(message_id="msg-timer-1", metrics=metrics)
    )

    # Before 500ms, should not be committed yet
    conn = sqlite3.connect(test_db)
    count_immediate = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[
        0
    ]
    conn.close()
    assert count_immediate == 0

    # Poll with timeout for timer flush (no fixed sleep depending on machine speed)
    start_time = asyncio.get_running_loop().time()
    count_after_timer = 0
    while asyncio.get_running_loop().time() - start_time < 3.0:
        await asyncio.sleep(0.05)
        conn = sqlite3.connect(test_db)
        count_after_timer = conn.execute(
            "SELECT COUNT(*) FROM telemetry_values"
        ).fetchone()[0]
        conn.close()
        if count_after_timer == 2:
            break

    await engine.stop()
    assert count_after_timer == 2


@pytest.mark.anyio
async def test_graceful_shutdown_drains_queue_and_loses_nothing(test_db):
    """Acceptance criterion: graceful shutdown drains the in-memory queue and commits final batch."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(
        test_db,
        plants=plants,
        batch_size=100,
        flush_interval_seconds=60.0,
    )
    await engine.start()

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
    metrics = {"mold_temperature_actual": 65.0, "vibration_mms": 1.5}
    # Enqueue 15 messages = 30 items (< batch_size 100, timer is 60s)
    for i in range(15):
        await engine.enqueue(
            topic, make_valid_payload(message_id=f"msg-drain-{i}", metrics=metrics)
        )

    # Stop engine: must drain and commit the 30 items
    await engine.stop()

    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM telemetry_values").fetchone()[0]
    conn.close()
    assert count == 30


@pytest.mark.anyio
async def test_tenant_and_asset_mismatch_rejected(test_db):
    """Acceptance criterion: tenant mismatch, unknown asset, or invalid schema rejected."""
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(test_db, plants=plants)

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"

    # Tenant mismatch
    mismatched_tenant = make_valid_payload(plant_id="plant_water_district_9")
    assert await engine.enqueue(topic, mismatched_tenant) is False

    # Unknown asset
    unknown_asset = make_valid_payload(asset_id="nonexistent_machine")
    assert (
        await engine.enqueue(
            "plants/plant_demo_membrane/assets/nonexistent_machine/telemetry",
            unknown_asset,
        )
        is False
    )

    # Invalid schema version
    bad_schema = make_valid_payload()
    bad_schema["schema_version"] = "2.0"
    assert await engine.enqueue(topic, bad_schema) is False


@pytest.mark.anyio
async def test_topic_router_ingest_integration(test_db):
    """Integration: TopicRouter dispatches telemetry directly into IngestEngine."""
    from topic_router import TopicRouter

    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(test_db, plants=plants)
    router = TopicRouter()
    router.on("telemetry")(engine.handle_telemetry)

    topic = "plants/plant_demo_membrane/assets/hm_01/telemetry"
    payload = make_valid_payload(message_id="msg-router-int-1")

    res = await router.dispatch(topic, payload)
    assert res is True

    await engine.flush()

    conn = sqlite3.connect(test_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM telemetry_values WHERE message_id = 'msg-router-int-1'"
    ).fetchone()[0]
    conn.close()
    assert count == 3
