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


def test_watchdog_heartbeats_while_capped_do_not_restart_early():
    """Heartbeats while capped do not restart it early; requires idle silence."""
    clock = SimulatedClock(0.0)
    wd = Watchdog(
        timeout_seconds=30.0,
        max_runtime_seconds=100.0,
        cap_reset_idle_seconds=600.0,
        clock=clock.time,
    )

    wd.on_heartbeat()
    clock.advance(105.0)
    wd.on_heartbeat()
    assert wd.cap_exceeded()
    assert not wd.should_run()

    # Heartbeats arrive every 60 seconds while capped (silence < 600s)
    for _ in range(5):
        clock.advance(60.0)
        wd.on_heartbeat()
        assert not wd.should_run()
        assert not wd.is_running()
        assert wd.cap_exceeded()


def test_watchdog_cap_resets_after_idle_period_and_new_heartbeat():
    """After configurable idle period (600s default) with no heartbeats, a new heartbeat starts fresh run."""
    clock = SimulatedClock(0.0)
    wd = Watchdog(
        timeout_seconds=30.0,
        max_runtime_seconds=100.0,
        cap_reset_idle_seconds=600.0,
        clock=clock.time,
    )

    # 1. Run until cap is hit
    wd.on_heartbeat()
    clock.advance(105.0)
    wd.on_heartbeat()
    assert not wd.should_run()
    assert wd.cap_exceeded()

    # 2. Heartbeat at t=110 while capped -> still capped
    clock.advance(5.0)
    wd.on_heartbeat()
    assert not wd.should_run()

    # 3. Idle period with NO heartbeats for 599s -> still cannot reset
    clock.advance(599.0)
    wd.on_heartbeat()
    assert not wd.should_run()
    assert wd.cap_exceeded()

    # 4. Now idle period with NO heartbeats for full 600s
    clock.advance(601.0)
    # A new heartbeat arrives after 601s of silence!
    wd.on_heartbeat()

    # Should have started a fresh run with accumulated runtime reset!
    assert wd.is_running()
    assert wd.should_run()
    assert not wd.cap_exceeded()
    assert wd._total_runtime < 10.0


def test_watchdog_cap_reset_idle_period_env_var(monkeypatch):
    """Configurable idle period via SIMULATOR_CAP_RESET_IDLE_SECONDS env var."""
    monkeypatch.setenv("SIMULATOR_CAP_RESET_IDLE_SECONDS", "300.0")
    wd = Watchdog()
    assert wd.cap_reset_idle_seconds == 300.0


def test_cap_reached_publishes_offline_states_for_all_machines():
    """When the cap is reached, OFFLINE states are published for all machines through existing state path."""
    import json
    from unittest.mock import MagicMock

    from demo.simulator.mqtt_publisher import publish_all_offline
    from demo.simulator.simulator import DemoSimulator
    from topic_router import TopicRouter

    sim = DemoSimulator(plant_id="plant_demo_membrane")
    mock_client = MagicMock()
    prev_states = {m.machine_id: "RUNNING" for m in sim.line.machines}
    prev_states.update({q.machine_id: "IDLE" for q in sim.line.qc_stations})

    publish_all_offline(mock_client, sim, "plant_demo_membrane", prev_states)

    router = TopicRouter()
    assert mock_client.publish.call_count == len(sim.line.machines) + len(
        sim.line.qc_stations
    )
    for call in mock_client.publish.call_args_list:
        topic, payload_str = call[0][0], call[0][1]
        payload = json.loads(payload_str)
        assert router.match(topic) is not None
        assert topic.endswith("/state")
        assert payload["payload_type"] == "state_change"
        assert payload["payload"]["status"] == "OFFLINE"


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


# ---------------------------------------------------------------------------
# Simulator Fault Recovery, Unit Preservation & 2-Hour Continuous Run Tests
# ---------------------------------------------------------------------------


def test_unit_not_lost_or_stranded_on_fault_and_repair():
    """Condition 2: An in-progress unit is returned to front of input queue upon repair and not lost."""
    clock = SimulatedClock(1000.0)
    sim = DemoSimulator(plant_id="plant_demo_membrane", clock=clock.time, seed=42)

    # Find a casting machine and stage a known unit in its input queue
    casting_m = next(m for m in sim.line.machines if m.sub_facility == "casting")
    from demo.simulator.units import Unit

    staged_unit = Unit()
    staged_unit_id = staged_unit.unit_id
    sim.line.queues["casting"].insert(0, staged_unit)

    # Run tick so casting machine picks up this unit
    sim.tick()
    assert casting_m.current_unit is not None
    assert casting_m.current_unit.unit_id == staged_unit_id

    # Induce a fault on this machine
    casting_m.vibration = casting_m.vibration_fault_threshold + 0.1
    casting_m.machine_state = "FAULT"
    casting_m.repair_elapsed = 0.0

    # Advance clock past repair delay (90s = 45 ticks)
    for _ in range(45):
        clock.advance(2.0)
        sim.tick()

    # Machine should now be repaired, state returns to IDLE, vibration reset
    assert casting_m.machine_state == "IDLE"
    assert casting_m.vibration <= 2.0

    # The in-progress unit must be returned to front of the casting queue, not lost or stranded
    assert len(sim.line.queues["casting"]) > 0
    assert sim.line.queues["casting"][0].unit_id == staged_unit_id
    assert casting_m.current_unit is None


def test_simulated_two_hours_production_and_fault_recovery():
    """Condition 4: Over simulated 2 hours with fake clock and fixed seed:
    - Every stage has at least one non-faulted machine at the end.
    - Completed units grow in each 15-minute window after the first 10 minutes.
    """
    clock = SimulatedClock(0.0)
    sim = DemoSimulator(plant_id="plant_demo_membrane", clock=clock.time, seed=42)

    total_ticks = 7200 // 2  # 3600 ticks of 2s = 7200s (2 hours)
    start_10m_tick = 600 // 2
    window_ticks = 900 // 2  # 15 minutes = 900s

    qc_prev = 0
    window_growths = []

    for tick in range(1, total_ticks + 1):
        clock.advance(2.0)
        sim.tick()

        if tick == start_10m_tick:
            qc_prev = sum(q.tested_count for q in sim.line.qc_stations)
        elif tick > start_10m_tick and (tick - start_10m_tick) % window_ticks == 0:
            qc_curr = sum(q.tested_count for q in sim.line.qc_stations)
            growth = qc_curr - qc_prev
            window_growths.append(growth)
            qc_prev = qc_curr

    # Assert completed units grew in each 15-minute window after the first 10 minutes
    assert len(window_growths) == 7  # 25m, 40m, 55m, 70m, 85m, 100m, 115m
    for i, growth in enumerate(window_growths):
        assert growth > 0, f"Window {i + 1} had zero unit growth ({growth})"

    # Assert every stage has at least one non-faulted machine at the end
    stages = ["housing", "casting", "assembly", "qc"]
    for stage in stages:
        if stage == "qc":
            healthy = [q for q in sim.line.qc_stations if q.machine_state != "FAULT"]
        else:
            healthy = [
                m
                for m in sim.line.machines
                if m.sub_facility == stage and m.machine_state != "FAULT"
            ]
        assert len(healthy) >= 1, (
            f"Stage {stage} has no healthy machines at end of 2h run"
        )


def test_repair_delay_and_drift_scale_env_vars(monkeypatch):
    """Condition 5: Environment variables SIMULATOR_REPAIR_DELAY_SECONDS and SIMULATOR_DRIFT_SCALE."""
    monkeypatch.setenv("SIMULATOR_REPAIR_DELAY_SECONDS", "45.0")
    monkeypatch.setenv("SIMULATOR_DRIFT_SCALE", "0.05")

    sim = DemoSimulator(plant_id="plant_demo_membrane")
    assert sim.repair_delay_seconds == 45.0
    assert sim.drift_scale == 0.05
