from datetime import UTC, datetime
from pathlib import Path

import pytest

from demo.simulator.watchdog import Watchdog
from demo.simulator.water_simulator import (
    WaterPlantSimulator,
    build_water_state_payload,
    build_water_telemetry_payload,
    load_water_credentials,
)
from ingest import IngestEngine
from plant_definitions import load_plants
from topic_router import TopicRouter

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"


def test_water_credentials_fail_startup_when_missing(monkeypatch):
    """Missing WATER_MQTT_USER, WATER_MQTT_PASSWORD, or WATER_MQTT_CLIENT_ID must fail at startup naming missing vars."""
    monkeypatch.delenv("WATER_MQTT_USER", raising=False)
    monkeypatch.delenv("WATER_MQTT_PASSWORD", raising=False)
    monkeypatch.delenv("WATER_MQTT_CLIENT_ID", raising=False)

    with pytest.raises(ValueError) as excinfo:
        load_water_credentials()
    assert "WATER_MQTT_USER" in str(excinfo.value)
    assert "WATER_MQTT_PASSWORD" in str(excinfo.value)
    assert "WATER_MQTT_CLIENT_ID" in str(excinfo.value)


def test_water_credentials_fail_when_password_missing_no_default(monkeypatch):
    """No default password in code; missing WATER_MQTT_PASSWORD must fail fast."""
    monkeypatch.setenv("WATER_MQTT_USER", "device_plant_water_district_9")
    monkeypatch.setenv("WATER_MQTT_CLIENT_ID", "gateway_district9_cellular")
    monkeypatch.delenv("WATER_MQTT_PASSWORD", raising=False)

    with pytest.raises(ValueError) as excinfo:
        load_water_credentials()
    assert "WATER_MQTT_PASSWORD" in str(excinfo.value)


def test_water_credentials_loaded_successfully(monkeypatch):
    """When all credentials are provided in env, load_water_credentials returns them."""
    monkeypatch.setenv("WATER_MQTT_USER", "device_plant_water_district_9")
    monkeypatch.setenv("WATER_MQTT_PASSWORD", "water_district_edge_key_771")
    monkeypatch.setenv("WATER_MQTT_CLIENT_ID", "gateway_district9_cellular")

    creds = load_water_credentials()
    assert creds["WATER_MQTT_USER"] == "device_plant_water_district_9"
    assert creds["WATER_MQTT_PASSWORD"] == "water_district_edge_key_771"
    assert creds["WATER_MQTT_CLIENT_ID"] == "gateway_district9_cellular"


def test_water_simulator_generates_plausible_values_for_9_signals():
    """Generates plausible values for 9 signals across 3 pumps conforming to plant definition and design doc.
    - pump_01 (5 signals): discharge_pressure_bar, flow_rate_m3h, motor_current_amps, bearing_temperature_c, vibration_rms_mms. RUNNING.
    - pump_02 (2 signals): discharge_pressure_bar, bearing_temperature_c. RUNNING.
    - pump_03 (2 signals): discharge_pressure_bar, bearing_temperature_c. STANDBY (low pressure, ambient temp).
    """
    sim = WaterPlantSimulator()
    readings = sim.tick()

    assert len(readings) == 3
    by_code = {r["machine_code"]: r for r in readings}

    # Verify pump_01
    p1 = by_code["pump_01"]
    assert p1["state"] == "RUNNING"
    p1_metrics = p1["metrics"]
    assert len(p1_metrics) == 5
    assert 3.8 <= p1_metrics["discharge_pressure_bar"] <= 4.5
    assert 120.0 <= p1_metrics["flow_rate_m3h"] <= 180.0
    assert 20.0 <= p1_metrics["motor_current_amps"] <= 35.0
    assert 45.0 <= p1_metrics["bearing_temperature_c"] <= 65.0
    assert 0.5 <= p1_metrics["vibration_rms_mms"] <= 3.5

    # Verify pump_02
    p2 = by_code["pump_02"]
    assert p2["state"] == "RUNNING"
    p2_metrics = p2["metrics"]
    assert len(p2_metrics) == 2
    assert 3.8 <= p2_metrics["discharge_pressure_bar"] <= 4.5
    assert 45.0 <= p2_metrics["bearing_temperature_c"] <= 65.0

    # Verify pump_03: Standby pump behavior
    p3 = by_code["pump_03"]
    assert p3["state"] == "STANDBY"
    p3_metrics = p3["metrics"]
    assert len(p3_metrics) == 2
    assert 0.0 <= p3_metrics["discharge_pressure_bar"] <= 1.0
    assert 18.0 <= p3_metrics["bearing_temperature_c"] <= 26.0

    # Total signal count
    total_signals = sum(len(r["metrics"]) for r in readings)
    assert total_signals == 9


def test_water_topics_and_payloads_pass_ingest_validation(tmp_path):
    """Payloads match TopicRouter and pass IngestEngine envelope validation."""
    sim = WaterPlantSimulator()
    readings = sim.tick()
    router = TopicRouter()
    plants = load_plants(PLANTS_DIR)
    engine = IngestEngine(tmp_path / "test.db", plants=plants)

    for r in readings:
        topic, payload = build_water_telemetry_payload(r)
        match = router.match(topic)
        assert match is not None
        assert match.route_type == "telemetry"
        assert match.params["plant_id"] == "plant_water_district_9"
        assert match.params["machine_code"] == r["machine_code"]

        # Validate against IngestEngine
        is_valid, reason, rows = engine._validate_envelope(
            topic, payload, datetime.now(UTC)
        )
        assert is_valid is True, f"Validation failed for {topic}: {reason}"
        assert len(rows) == len(r["metrics"])

    # Test state payload
    s_topic, s_payload = build_water_state_payload(
        plant_id="plant_water_district_9",
        machine_code="pump_03",
        previous_status=None,
        status="STANDBY",
    )
    s_match = router.match(s_topic)
    assert s_match is not None
    assert s_match.route_type == "state"
    assert s_match.params["plant_id"] == "plant_water_district_9"
    assert s_match.params["machine_code"] == "pump_03"
    assert s_payload["payload_type"] == "state_change"
    assert s_payload["payload"]["status"] == "STANDBY"


def test_water_simulator_gated_by_watchdog():
    """Water plant publishing only runs while watchdog is active."""

    class FakeClock:
        def __init__(self):
            self._time = 1000.0

        def __call__(self):
            return self._time

        def advance(self, s):
            self._time += s

    clock = FakeClock()
    wd = Watchdog(timeout_seconds=30.0, max_runtime_seconds=7200.0, clock=clock)
    assert not wd.should_run()

    # Simulator loop check: when wd.should_run() is False, no water tick is performed
    ticks_published = 0
    sim = WaterPlantSimulator()

    for _ in range(5):
        if wd.should_run():
            sim.tick()
            ticks_published += 1
    assert ticks_published == 0

    # Heartbeat arrives -> watchdog active
    wd.on_heartbeat()
    assert wd.should_run()
    for _ in range(5):
        if wd.should_run():
            sim.tick()
            ticks_published += 1
    assert ticks_published == 5
