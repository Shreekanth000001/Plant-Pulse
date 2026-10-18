import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from demo.simulator.simulator import (
    DemoSimulator,
    build_qc_result_payload,
    build_queue_depths_payload,
    build_stage_event_payload,
    build_state_payload,
    build_telemetry_payload,
    load_simulator_credentials,
)
from demo.simulator.watchdog import Watchdog
from ingest import IngestEngine
from main import (
    DEMO_PLANT_ID,
    ConnectionManager,
    emit_heartbeat_tick,
)
from plant_definitions import load_plants
from topic_router import TopicRouter

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"


# ---------------------------------------------------------------------------
# Criterion 5 & 3: Watchdog with Injectable Clock & Run-Time Cap
# ---------------------------------------------------------------------------


class SimulatedClock:
    """Injectable clock for deterministic time manipulation without sleeps."""

    def __init__(self, start_time: float = 1000.0):
        self._current_time = start_time

    def time(self) -> float:
        return self._current_time

    def advance(self, seconds: float) -> None:
        self._current_time += seconds


def test_watchdog_starts_idle():
    """Watchdog begins in an idle/stopped state until first heartbeat."""
    clock = SimulatedClock(1000.0)
    wd = Watchdog(timeout_seconds=30.0, max_runtime_seconds=7200.0, clock=clock.time)
    assert not wd.is_running()
    assert not wd.should_run()


def test_watchdog_resumes_on_heartbeat_and_tears_down_after_silence():
    """Heartbeat triggers running; 30s silence triggers teardown; next heartbeat resumes."""
    clock = SimulatedClock(1000.0)
    wd = Watchdog(timeout_seconds=30.0, max_runtime_seconds=7200.0, clock=clock.time)

    # Initial state
    assert not wd.should_run()

    # Heartbeat arrives at t=1000.0
    wd.on_heartbeat()
    assert wd.is_running()
    assert wd.should_run()

    # Advance 20 seconds (under 30s timeout)
    clock.advance(20.0)
    assert wd.should_run()
    assert wd.is_running()

    # Advance another 11 seconds (total 31s since last heartbeat) -> triggers teardown
    clock.advance(11.0)
    assert not wd.should_run()
    assert not wd.is_running()

    # Next heartbeat arrives at t=1031.0 -> resumes immediately
    wd.on_heartbeat()
    assert wd.is_running()
    assert wd.should_run()


def test_watchdog_runtime_cap_stops_even_with_continuous_heartbeats():
    """Criterion 3: Simulator stops after configured max runtime (7200s) even if heartbeats continue."""
    clock = SimulatedClock(0.0)
    # Set cap to 100.0s for testing
    wd = Watchdog(timeout_seconds=30.0, max_runtime_seconds=100.0, clock=clock.time)

    # Start with heartbeat
    wd.on_heartbeat()
    assert wd.is_running()

    # Simulate heartbeats every 5 seconds for 95 seconds
    for _ in range(19):
        clock.advance(5.0)
        wd.on_heartbeat()
        assert wd.should_run()

    # Now at t=95. Advance 10 more seconds to t=105 (exceeding 100s cap)
    clock.advance(10.0)
    wd.on_heartbeat()  # Heartbeat still arrives!
    # Cap exceeded: must stop and refuse to run even though heartbeat arrived
    assert not wd.should_run()
    assert not wd.is_running()
    assert wd.cap_exceeded()


# ---------------------------------------------------------------------------
# Criterion 2: Missing MQTT Credentials Fail Startup With Clear Error
# ---------------------------------------------------------------------------


def test_missing_mqtt_credentials_fail_startup():
    """Missing MQTT_USER, MQTT_PASSWORD or MQTT_CLIENT_ID fails startup clearly."""
    env = {
        "MQTT_USER": "test_user",
        "MQTT_CLIENT_ID": "test_client",
        # MQTT_PASSWORD omitted
    }
    with (
        patch.dict(os.environ, env, clear=True),
        pytest.raises(ValueError, match="MQTT_PASSWORD"),
    ):
        load_simulator_credentials()


def test_no_default_password_in_credentials():
    """No default password exists; all credentials must come strictly from environment."""
    env = {"MQTT_USER": "test_user"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError) as excinfo:
            load_simulator_credentials()
        msg = str(excinfo.value)
        assert "MQTT_PASSWORD" in msg
        assert "MQTT_CLIENT_ID" in msg


# ---------------------------------------------------------------------------
# Criterion 4: Topics Matched by TopicRouter & Payloads Pass Ingest Validation
# ---------------------------------------------------------------------------


def test_every_simulator_topic_matches_topic_router():
    """Every topic published by the simulator matches TopicRouter patterns from section 4.1."""
    router = TopicRouter()
    sim = DemoSimulator(plant_id="plant_demo_membrane")

    topics = sim.get_all_publish_topics()
    assert len(topics) >= 11  # At least all 11 machines telemetry

    for topic in topics:
        match = router.match(topic)
        assert match is not None, f"Topic '{topic}' failed to match TopicRouter"


def test_telemetry_payloads_pass_ingest_envelope_validation(tmp_path):
    """Telemetry payloads from simulator pass IngestEngine envelope validation for all 11 machines."""
    db_file = tmp_path / "test_sim_ingest.db"
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(db_path=db_file, plants=plants)

    sim = DemoSimulator(plant_id="plant_demo_membrane")
    plant_def = plants["plant_demo_membrane"]

    # Gather machine codes from plant definition
    expected_machines = {
        m.machine_code for area in plant_def.areas for m in area.machines
    }
    assert len(expected_machines) == 11

    now = datetime.now(UTC)
    readings = sim.tick()
    assert len(readings) == 11

    for reading in readings:
        topic, payload = build_telemetry_payload(
            reading, plant_id="plant_demo_membrane"
        )
        valid, reason, rows = engine._validate_envelope(topic, payload, now)
        assert valid is True, f"Failed for {topic}: {reason}"
        assert len(rows) > 0
        # Ensure asset matches
        assert payload["asset_id"] in expected_machines


def test_other_simulator_event_payloads_match_section_4():
    """Verify state change, stage event, qc result, and queue depths match design doc."""
    router = TopicRouter()

    # 1. State change topic & payload
    state_topic, state_payload = build_state_payload(
        plant_id="plant_demo_membrane",
        machine_code="hm_01",
        previous_status="IDLE",
        status="RUNNING",
    )
    assert router.match(state_topic) is not None
    assert state_payload["payload_type"] == "state_change"

    # 2. Stage event
    stage_topic, stage_payload = build_stage_event_payload(
        plant_id="plant_demo_membrane",
        machine_code="cs_01",
        area_code="casting",
        unit_id="unit_123",
        outcome="ok",
        anomaly_score=0.1,
        readings={"viscosity_actual": 34.0},
    )
    assert router.match(stage_topic) is not None
    assert stage_payload["payload_type"] == "stage_event"

    # 3. QC result
    qc_topic, qc_payload = build_qc_result_payload(
        plant_id="plant_demo_membrane",
        machine_code="qc_01",
        unit_id="unit_123",
        outcome="fail",
        probability=0.45,
        defect_type="THICKNESS_DEVIATION",
        attributed_stage="casting",
    )
    assert router.match(qc_topic) is not None
    assert qc_payload["payload_type"] == "qc_result"

    # 4. Queue depths
    q_topic, q_payload = build_queue_depths_payload(
        plant_id="plant_demo_membrane",
        queue_depths={"casting": 2, "assembly": 1, "qc": 0},
    )
    assert router.match(q_topic) is not None
    assert q_payload["payload_type"] == "queue_depths"


# ---------------------------------------------------------------------------
# Criterion 6: Heartbeat Emitter in main.py
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_heartbeat_emitter_emits_when_demo_plant_has_viewers():
    """Heartbeat tick emits plants/plant_demo_membrane/control/heartbeat when demo viewers > 0."""
    mock_publish = AsyncMock()
    test_manager = ConnectionManager()

    # Fake a connected client to demo plant
    mock_ws = AsyncMock()
    await test_manager.connect_plant(DEMO_PLANT_ID, mock_ws)

    emitted = await emit_heartbeat_tick(test_manager, publish_fn=mock_publish)
    assert emitted is True
    mock_publish.assert_called_once()
    args, _kwargs = mock_publish.call_args
    topic, payload_str = args
    assert topic == f"plants/{DEMO_PLANT_ID}/control/heartbeat"
    assert "timestamp" in payload_str


@pytest.mark.anyio
async def test_heartbeat_emitter_silent_when_no_viewers():
    """Heartbeat tick does not emit when no viewers are connected to demo plant."""
    mock_publish = AsyncMock()
    test_manager = ConnectionManager()

    emitted = await emit_heartbeat_tick(test_manager, publish_fn=mock_publish)
    assert emitted is False
    mock_publish.assert_not_called()


# ---------------------------------------------------------------------------
# Criterion 5 & 1 & 2: Monotonic Clock, Runner Entrypoint, Backend MQTT Auth
# ---------------------------------------------------------------------------


def test_watchdog_default_clock_is_time_monotonic():
    """Criterion 5: Watchdog default clock must be time.monotonic."""
    import time

    wd = Watchdog()
    assert wd.clock == time.monotonic


def test_simulator_runner_entrypoint_exists():
    """Criterion 2: demo/simulator/runner.py runnable entrypoint exists."""
    from demo.simulator import runner

    assert hasattr(runner, "main")
    assert callable(runner.main)


def test_main_backend_mqtt_client_uses_env_credentials(monkeypatch):
    """Criterion 1: main.py passes MQTT_USER and MQTT_PASSWORD to aiomqtt.Client."""
    from main import get_mqtt_credentials

    monkeypatch.setenv("MQTT_USER", "backend_service")
    monkeypatch.setenv("MQTT_PASSWORD", "backend_secret")

    user, password = get_mqtt_credentials()
    assert user == "backend_service"
    assert password == "backend_secret"
