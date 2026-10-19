"""Water Booster Pump Station simulator for District 9 (3 pumps, 9 signals).

Conforms to section 4.1, 4.2, 5.3 of docs/design/multi-plant-platform.md and
plants/plant_water_district_9.json.
"""

import os
import random
import uuid
from datetime import UTC, datetime


def load_water_credentials() -> dict[str, str]:
    """Read Water Plant MQTT credentials from environment.

    No default password in code, Dockerfile, or logs.
    Fails at startup with a clear message naming missing variables.
    """
    user = os.getenv("WATER_MQTT_USER")
    password = os.getenv("WATER_MQTT_PASSWORD")
    client_id = os.getenv("WATER_MQTT_CLIENT_ID")

    missing = []
    if not user:
        missing.append("WATER_MQTT_USER")
    if not password:
        missing.append("WATER_MQTT_PASSWORD")
    if not client_id:
        missing.append("WATER_MQTT_CLIENT_ID")

    if missing:
        raise ValueError(
            f"Missing required Water MQTT environment variables: {', '.join(missing)}. "
            "Please configure these credentials before starting the simulator."
        )

    return {
        "WATER_MQTT_USER": user,
        "WATER_MQTT_PASSWORD": password,
        "WATER_MQTT_CLIENT_ID": client_id,
    }


class WaterPlantSimulator:
    """Simulates 3 centrifugal pumps for plant_water_district_9.

    - pump_01: Main Intake Pump P-101 (RUNNING, 5 signals)
    - pump_02: Secondary Booster P-102 (RUNNING, 2 signals)
    - pump_03: Standby Booster P-103 (STANDBY, 2 signals)
    Total 9 signals.
    """

    def __init__(self, plant_id: str = "plant_water_district_9"):
        self.plant_id = plant_id

    def tick(self, now: datetime | None = None) -> list[dict]:
        ts = now or datetime.now(UTC)

        # 1. pump_01: Lead intake pump (RUNNING, 5 signals)
        p1_pressure = round(random.uniform(4.05, 4.25), 2)
        p1_flow = round(random.uniform(142.0, 155.0), 1)
        p1_current = round(random.uniform(27.0, 30.0), 1)
        p1_temp = round(random.uniform(53.0, 56.0), 1)
        p1_vib = round(random.uniform(1.3, 1.6), 2)

        p1 = {
            "machine_code": "pump_01",
            "state": "RUNNING",
            "metrics": {
                "discharge_pressure_bar": p1_pressure,
                "flow_rate_m3h": p1_flow,
                "motor_current_amps": p1_current,
                "bearing_temperature_c": p1_temp,
                "vibration_rms_mms": p1_vib,
            },
            "timestamp": ts,
        }

        # 2. pump_02: Secondary booster (RUNNING, 2 signals)
        p2_pressure = round(random.uniform(4.0, 4.2), 2)
        p2_temp = round(random.uniform(52.0, 55.0), 1)

        p2 = {
            "machine_code": "pump_02",
            "state": "RUNNING",
            "metrics": {
                "discharge_pressure_bar": p2_pressure,
                "bearing_temperature_c": p2_temp,
            },
            "timestamp": ts,
        }

        # 3. pump_03: Standby booster (STANDBY, 2 signals)
        # Standby behavior: low residual pressure (0.0-0.4 bar), ambient temperature (21-23 C)
        p3_pressure = round(random.uniform(0.1, 0.3), 2)
        p3_temp = round(random.uniform(21.0, 23.0), 1)

        p3 = {
            "machine_code": "pump_03",
            "state": "STANDBY",
            "metrics": {
                "discharge_pressure_bar": p3_pressure,
                "bearing_temperature_c": p3_temp,
            },
            "timestamp": ts,
        }

        return [p1, p2, p3]


def build_water_telemetry_payload(
    reading: dict, plant_id: str = "plant_water_district_9"
) -> tuple[str, dict]:
    """Build canonical telemetry payload conforming to Section 4.1/4.2."""
    machine_code = reading["machine_code"]
    topic = f"plants/{plant_id}/assets/{machine_code}/telemetry"
    ts_iso = (
        reading["timestamp"].isoformat()
        if hasattr(reading["timestamp"], "isoformat")
        else str(reading["timestamp"])
    )

    payload = {
        "schema_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "plant_id": plant_id,
        "asset_id": machine_code,
        "device_timestamp": ts_iso,
        "payload_type": "telemetry",
        "payload": {
            "status": reading["state"],
            "metrics": reading["metrics"],
        },
    }
    return topic, payload


def build_water_state_payload(
    plant_id: str,
    machine_code: str,
    previous_status: str | None,
    status: str,
    sub_status: str | None = None,
    timestamp: datetime | None = None,
) -> tuple[str, dict]:
    """Build canonical state payload conforming to Section 4.1/4.2."""
    topic = f"plants/{plant_id}/assets/{machine_code}/state"
    ts = timestamp or datetime.now(UTC)

    payload = {
        "schema_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "plant_id": plant_id,
        "asset_id": machine_code,
        "device_timestamp": ts.isoformat(),
        "payload_type": "state_change",
        "payload": {
            "previous_status": previous_status or "OFFLINE",
            "status": status,
            "sub_status": sub_status,
        },
    }
    return topic, payload
