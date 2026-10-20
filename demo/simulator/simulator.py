"""Demo simulator for Membrane Manufacturing Facility (11 machines).

Decoupled platform client that runs in demo/simulator/.
Publishes canonical MQTT topics scoped under plants/{plant_id}/... conforming to
section 4.1 and section 4.2 of docs/design/multi-plant-platform.md.
"""

import os
import random
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

try:
    from demo.simulator.config import FACILITY
    from demo.simulator.defect_model import decide_outcome, pick_defect_type
    from demo.simulator.units import Unit
except ImportError:
    from config import FACILITY
    from defect_model import decide_outcome, pick_defect_type
    from units import Unit

TICK_SECONDS = 2
STAGE_ORDER = ["housing", "casting", "assembly", "qc"]

DEFECT_TYPES_BY_STAGE = {
    sf["stage_type"]: sf["machines"][0]["defect_types"]
    for sf in FACILITY["sub_facilities"]
    if sf["stage_type"] != "qc"
}


def load_simulator_credentials() -> dict[str, str]:
    """Read MQTT credentials from the environment.

    No default password in code, Dockerfile, or logs.
    Fails at startup with a clear message naming missing variables.
    """
    user = os.getenv("MQTT_USER")
    password = os.getenv("MQTT_PASSWORD")
    client_id = os.getenv("MQTT_CLIENT_ID")

    missing = []
    if not user:
        missing.append("MQTT_USER")
    if not password:
        missing.append("MQTT_PASSWORD")
    if not client_id:
        missing.append("MQTT_CLIENT_ID")

    if missing:
        raise ValueError(
            f"Missing required MQTT environment variables: {', '.join(missing)}. "
            "Please configure these credentials before starting the demo simulator."
        )

    return {
        "MQTT_USER": user,
        "MQTT_PASSWORD": password,
        "MQTT_CLIENT_ID": client_id,
    }


class MachineSim:
    def __init__(
        self,
        machine_id: str,
        name: str,
        sub_facility: str,
        readings: dict,
        phases: list[str],
        vibration_fault_threshold: float,
        cycle_time_mean: float,
        cycle_time_std: float,
        input_queue: list[Unit] | None,
        output_queue: list[Unit] | None,
        repair_delay_seconds: float = 90.0,
        drift_scale: float = 0.1,
        initial_vibration: float = 0.2,
        clock: Callable[[], float] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.machine_id = machine_id
        self.name = name
        self.sub_facility = sub_facility
        self.readings = readings
        self.cycle_time_mean = cycle_time_mean
        self.cycle_time_std = cycle_time_std
        self.vibration_fault_threshold = vibration_fault_threshold
        self.repair_delay_seconds = repair_delay_seconds
        self.drift_scale = drift_scale
        self.clock = clock
        self.rng = rng or random.Random()

        self.input_queue = input_queue
        self.output_queue = output_queue

        self.phases = phases
        self.phase_index = 0
        self.phase_elapsed = 0.0
        self._working_phase_count = sum(1 for p in phases if p != "IDLE")

        self.phase_duration = self._roll_phase_duration()
        self.machine_state = "IDLE"
        self.starved = False
        self.vibration = initial_vibration
        self.vibration_wear_level = 0.0
        self.good_count = 0
        self.reject_count = 0

        self.current_unit: Unit | None = None
        self._cycle_started_at: float | None = None
        self._last_stage_event: dict | None = None
        self.repair_elapsed = 0.0

    @property
    def phase(self) -> str:
        return self.phases[self.phase_index]

    def _roll_phase_duration(self) -> float:
        cycle_time = max(
            self.rng.gauss(self.cycle_time_mean, self.cycle_time_std), 10.0
        )
        return cycle_time / self._working_phase_count

    def _try_start_cycle(self) -> bool:
        if self.input_queue is not None and self.input_queue:
            self.current_unit = self.input_queue.pop(0)
        elif self.sub_facility == "housing":
            self.current_unit = Unit()
        else:
            self.starved = True
            return False

        self.starved = False
        self._cycle_started_at = self.clock() if self.clock else time.time()
        self.phase_index = (self.phase_index + 1) % len(self.phases)
        self.phase_elapsed = 0.0
        self.phase_duration = self._roll_phase_duration()
        return True

    def _advance_phase(self) -> None:
        self.phase_index = (self.phase_index + 1) % len(self.phases)
        self.phase_elapsed = 0.0
        self.phase_duration = self._roll_phase_duration()

        if self.phase == "IDLE":
            self._complete_unit()

    def _complete_unit(self) -> None:
        defect_chance = 0.03 + max(0.0, (self.vibration - 4.0) * 0.03)
        outcome = "flagged" if self.rng.random() < defect_chance else "ok"

        if outcome == "flagged":
            self.reject_count += 1
        else:
            self.good_count += 1

        unit = self.current_unit
        snapshot, anomaly_score = self._snapshot_readings()
        exited_at = self.clock() if self.clock else time.time()
        unit.record_stage(
            sub_facility=self.sub_facility,
            machine_id=self.machine_id,
            entered_at=self._cycle_started_at,
            exited_at=exited_at,
            readings=snapshot,
            outcome=outcome,
            anomaly_score=anomaly_score,
        )

        self._last_stage_event = {
            "unit_id": unit.unit_id,
            "sub_facility": self.sub_facility,
            "machine_id": self.machine_id,
            "entered_at": self._cycle_started_at,
            "exited_at": exited_at,
            "readings": snapshot,
            "outcome": outcome,
            "anomaly_score": round(anomaly_score, 3),
        }

        if self.output_queue is not None:
            self.output_queue.append(unit)

        self.current_unit = None

    def _snapshot_readings(self) -> tuple[dict, float]:
        snapshot = {}
        anomaly_score = 0.0
        for name, (setpoint, std) in self.readings.items():
            actual = self.rng.gauss(setpoint, std)
            snapshot[name] = round(actual, 2)
            if std > 0:
                anomaly_score += abs(actual - setpoint) / std
        return snapshot, anomaly_score

    def _update_vibration(self) -> None:
        if self.vibration < 10:
            self.vibration += self.rng.uniform(0, 0.1) * self.drift_scale
        self.vibration_wear_level += self.vibration * 0.01

        if self.vibration > self.vibration_fault_threshold:
            self.machine_state = "FAULT"
            self.repair_elapsed = 0.0

    def tick(self) -> dict:
        self._last_stage_event = None

        if self.machine_state == "FAULT":
            self.repair_elapsed += TICK_SECONDS
            if self.repair_elapsed >= self.repair_delay_seconds:
                # Repair complete: preserve in-progress unit, reset vibration, return to IDLE
                if self.current_unit is not None:
                    if self.input_queue is not None:
                        self.input_queue.insert(0, self.current_unit)
                    self.current_unit = None
                self.vibration = 0.2
                self.machine_state = "IDLE"
                self.phase_index = 0
                self.phase_elapsed = 0.0
                self.starved = False
                self.repair_elapsed = 0.0
        else:
            if self.phase == "IDLE":
                started = self._try_start_cycle()
                self.machine_state = "RUNNING" if started else "IDLE"
            else:
                self.machine_state = "RUNNING"
                self._update_vibration()
                self.phase_elapsed += TICK_SECONDS
                if self.phase_elapsed >= self.phase_duration:
                    self._advance_phase()

        reading = {
            "stage_event": self._last_stage_event,
            "machine_id": self.machine_id,
            "name": self.name,
            "machine_state": self.machine_state,
            "phase": self.phase,
            "starved": self.starved,
            "current_unit": self.current_unit.unit_id if self.current_unit else None,
            "vibration_mms": round(self.vibration, 2),
            "vibration": round(self.vibration, 2),
            "vibration_wear_level": round(self.vibration_wear_level, 3),
            "good_count": self.good_count,
            "reject_count": self.reject_count,
        }

        for field_name, (setpoint, std) in self.readings.items():
            actual = self.rng.gauss(setpoint, std)
            reading[f"{field_name}_setpoint"] = setpoint
            reading[f"{field_name}_actual"] = round(actual, 2)

        return reading


class QCStation:
    def __init__(
        self,
        machine_id: str,
        name: str,
        input_queue: list[Unit],
        test_duration_mean: float,
        test_duration_std: float,
        rng: random.Random | None = None,
    ) -> None:
        self.machine_id = machine_id
        self.name = name
        self.input_queue = input_queue
        self.test_duration_mean = test_duration_mean
        self.test_duration_std = test_duration_std
        self.rng = rng or random.Random()

        self.machine_state = "IDLE"
        self.starved = False
        self.current_unit: Unit | None = None
        self._test_elapsed = 0.0
        self._test_duration = 0.0

        self.tested_count = 0
        self.passed_count = 0
        self.failed_count = 0

    def _try_start_test(self) -> bool:
        if not self.input_queue:
            self.starved = True
            return False
        self.starved = False
        self.current_unit = self.input_queue.pop(0)
        self._test_elapsed = 0.0
        self._test_duration = max(
            self.rng.gauss(self.test_duration_mean, self.test_duration_std), 5.0
        )
        return True

    def _finish_test(self) -> dict:
        unit = self.current_unit
        current_hour = time.localtime().tm_hour
        outcome, probability = decide_outcome(unit, current_hour)

        result = {
            "unit_id": unit.unit_id,
            "outcome": outcome,
            "probability": round(probability, 3),
        }

        if outcome == "fail":
            failed_stage = pick_defect_type(unit)
            defect_type = self.rng.choice(DEFECT_TYPES_BY_STAGE[failed_stage])
            unit.status = "failed"
            result["defect_type"] = defect_type
            result["attributed_stage"] = failed_stage
            self.failed_count += 1
        else:
            unit.status = "passed"
            self.passed_count += 1

        self.tested_count += 1
        self.current_unit = None
        return result

    def tick(self) -> dict:
        last_result = None

        if self.machine_state == "IDLE":
            started = self._try_start_test()
            self.machine_state = "TESTING" if started else "IDLE"
        else:
            self._test_elapsed += TICK_SECONDS
            if self._test_elapsed >= self._test_duration:
                last_result = self._finish_test()
                self.machine_state = "IDLE"

        return {
            "machine_id": self.machine_id,
            "name": self.name,
            "machine_state": self.machine_state,
            "starved": self.starved,
            "current_unit": self.current_unit.unit_id if self.current_unit else None,
            "tested_count": self.tested_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "last_result": last_result,
            "test_duration": round(
                self._test_duration if self.machine_state == "TESTING" else 20.0, 2
            ),
            "vibration_mms": round(random.uniform(0.1, 0.5), 2),
        }


def _extract_readings(machine_config: dict) -> dict:
    readings = {}
    for key, value in machine_config.items():
        if key.endswith("_setpoint"):
            base_name = key[: -len("_setpoint")]
            std_key = f"{base_name}_normal_std"
            if std_key in machine_config:
                readings[base_name] = (value, machine_config[std_key])
    return readings


class Line:
    def __init__(
        self,
        repair_delay_seconds: float = 90.0,
        drift_scale: float = 0.1,
        clock: Callable[[], float] | None = None,
        seed: int | None = None,
    ) -> None:
        self.repair_delay_seconds = repair_delay_seconds
        self.drift_scale = drift_scale
        self.clock = clock
        self.seed = seed
        self.base_rng = random.Random(seed) if seed is not None else random.Random()

        self.queues: dict[str, list[Unit]] = {stage: [] for stage in STAGE_ORDER}
        self.machines: list[MachineSim] = []
        self.qc_stations: list[QCStation] = []
        self._build_machines()

    def _build_machines(self) -> None:
        sub_facilities_by_type = {
            sf["stage_type"]: sf for sf in FACILITY["sub_facilities"]
        }

        # Staggered initial vibrations: hm_01 starts pre-worn at 5.8
        # so it faults around 7-8 minutes into a cold start, matching live stack evidence.
        # Other machines start at normal/low baselines.
        initial_vibrations = {
            "hm_01": 6.3,
            "hm_02": 2.0,
            "cs_01": 2.0,
            "cs_02": 1.0,
            "am_01": 1.5,
            "am_02": 1.0,
            "am_03": 0.5,
            "am_04": 0.2,
        }

        m_idx = 0
        for stage_type in STAGE_ORDER:
            sf = sub_facilities_by_type[stage_type]

            if stage_type == "qc":
                for m in sf["machines"]:
                    qc_rng = (
                        random.Random(self.base_rng.randint(0, 1_000_000))
                        if self.seed is not None
                        else None
                    )
                    self.qc_stations.append(
                        QCStation(
                            machine_id=m["machine_id"],
                            name=m["name"],
                            input_queue=self.queues["qc"],
                            test_duration_mean=m["test_duration_mean"],
                            test_duration_std=m["test_duration_std"],
                            rng=qc_rng,
                        )
                    )
                continue

            stage_pos = STAGE_ORDER.index(stage_type)
            next_stage = STAGE_ORDER[stage_pos + 1]

            input_queue = self.queues[stage_type]
            output_queue = self.queues[next_stage]

            for m in sf["machines"]:
                m_rng = (
                    random.Random(self.base_rng.randint(0, 1_000_000))
                    if self.seed is not None
                    else None
                )
                init_vib = initial_vibrations.get(m["machine_id"], 0.2)
                # Stagger drift slightly per machine
                m_drift = self.drift_scale * (0.9 + (m_idx % 3) * 0.1)

                self.machines.append(
                    MachineSim(
                        machine_id=m["machine_id"],
                        name=m["name"],
                        sub_facility=stage_type,
                        readings=_extract_readings(m),
                        phases=sf["phases"],
                        vibration_fault_threshold=m["vibration_fault_threshold"],
                        cycle_time_mean=m["cycle_time_mean"],
                        cycle_time_std=m["cycle_time_std"],
                        input_queue=input_queue,
                        output_queue=output_queue,
                        repair_delay_seconds=self.repair_delay_seconds,
                        drift_scale=m_drift,
                        initial_vibration=init_vib,
                        clock=self.clock,
                        rng=m_rng,
                    )
                )
                m_idx += 1

    def tick(self) -> list[dict]:
        readings = [m.tick() for m in self.machines]
        readings += [q.tick() for q in self.qc_stations]
        return readings

    def queue_depths(self) -> dict:
        return {stage: len(q) for stage, q in self.queues.items() if stage != "housing"}


class DemoSimulator:
    def __init__(
        self,
        plant_id: str = "plant_demo_membrane",
        repair_delay_seconds: float | None = None,
        drift_scale: float | None = None,
        clock: Callable[[], float] | None = None,
        seed: int | None = None,
    ) -> None:
        self.plant_id = plant_id
        self.repair_delay_seconds = (
            repair_delay_seconds
            if repair_delay_seconds is not None
            else float(
                os.getenv(
                    "SIMULATOR_REPAIR_DELAY_SECONDS",
                    os.getenv("REPAIR_DELAY_SECONDS", "90.0"),
                )
            )
        )
        self.drift_scale = (
            drift_scale
            if drift_scale is not None
            else float(
                os.getenv(
                    "SIMULATOR_DRIFT_SCALE",
                    os.getenv("SIMULATOR_VIBRATION_DRIFT_SCALE", "0.1"),
                )
            )
        )
        self.clock = clock
        self.seed = seed
        self.line = Line(
            repair_delay_seconds=self.repair_delay_seconds,
            drift_scale=self.drift_scale,
            clock=self.clock,
            seed=self.seed,
        )
        self._prev_states: dict[str, str] = {}

    def tick(self) -> list[dict]:
        return self.line.tick()

    def queue_depths(self) -> dict:
        return self.line.queue_depths()

    def get_all_publish_topics(self) -> list[str]:
        topics = []
        for m in self.line.machines:
            topics.append(f"plants/{self.plant_id}/assets/{m.machine_id}/telemetry")
            topics.append(f"plants/{self.plant_id}/assets/{m.machine_id}/state")
        for q in self.line.qc_stations:
            topics.append(f"plants/{self.plant_id}/assets/{q.machine_id}/telemetry")
            topics.append(f"plants/{self.plant_id}/assets/{q.machine_id}/state")

        topics.append(f"plants/{self.plant_id}/modules/traceability/stage_event")
        topics.append(f"plants/{self.plant_id}/modules/traceability/queue_depths")
        topics.append(f"plants/{self.plant_id}/modules/quality/qc_result")
        return topics


# ---------------------------------------------------------------------------
# Envelope & Topic Builders conforming to Section 4.1 & 4.2
# ---------------------------------------------------------------------------


def build_telemetry_payload(
    reading: dict, plant_id: str = "plant_demo_membrane"
) -> tuple[str, dict]:
    machine_code = reading["machine_id"]
    topic = f"plants/{plant_id}/assets/{machine_code}/telemetry"

    # Extract metrics matching schema
    excluded = {
        "machine_id",
        "name",
        "machine_state",
        "phase",
        "starved",
        "current_unit",
        "stage_event",
        "last_result",
        "tested_count",
        "passed_count",
        "failed_count",
        "vibration_wear_level",
        "good_count",
        "reject_count",
    }
    metrics = {
        k: v
        for k, v in reading.items()
        if k not in excluded and isinstance(v, (int, float))
    }

    payload = {
        "schema_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "plant_id": plant_id,
        "asset_id": machine_code,
        "device_timestamp": datetime.now(UTC).isoformat(),
        "payload_type": "telemetry",
        "payload": {
            "status": reading.get("machine_state", "IDLE"),
            "sub_status": reading.get("phase"),
            "metrics": metrics,
        },
    }
    return topic, payload


def build_state_payload(
    plant_id: str,
    machine_code: str,
    previous_status: str | None = None,
    status: str = "IDLE",
    sub_status: str | None = None,
) -> tuple[str, dict]:
    topic = f"plants/{plant_id}/assets/{machine_code}/state"
    payload = {
        "schema_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "plant_id": plant_id,
        "asset_id": machine_code,
        "device_timestamp": datetime.now(UTC).isoformat(),
        "payload_type": "state_change",
        "payload": {
            "previous_status": previous_status or "IDLE",
            "status": status,
        },
    }
    if sub_status:
        payload["payload"]["sub_status"] = sub_status
    return topic, payload


def build_stage_event_payload(
    plant_id: str,
    machine_code: str,
    area_code: str,
    unit_id: str,
    outcome: str,
    anomaly_score: float,
    readings: dict[str, Any],
    entered_at: float | None = None,
    exited_at: float | None = None,
    is_starved: bool = False,
) -> tuple[str, dict]:
    topic = f"plants/{plant_id}/modules/traceability/stage_event"
    now_iso = datetime.now(UTC).isoformat()
    entered_iso = (
        datetime.fromtimestamp(entered_at, tz=UTC).isoformat()
        if entered_at
        else now_iso
    )
    exited_iso = (
        datetime.fromtimestamp(exited_at, tz=UTC).isoformat() if exited_at else now_iso
    )

    payload = {
        "schema_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "plant_id": plant_id,
        "asset_id": machine_code,
        "device_timestamp": now_iso,
        "payload_type": "stage_event",
        "payload": {
            "unit_id": unit_id,
            "machine_code": machine_code,
            "area_code": area_code,
            "is_starved": is_starved,
            "entered_at": entered_iso,
            "exited_at": exited_iso,
            "outcome": outcome,
            "anomaly_score": round(anomaly_score, 3),
            "sensor_snapshot": readings,
        },
    }
    return topic, payload


def build_qc_result_payload(
    plant_id: str,
    machine_code: str,
    unit_id: str,
    outcome: str,
    probability: float,
    defect_type: str | None = None,
    attributed_stage: str | None = None,
) -> tuple[str, dict]:
    topic = f"plants/{plant_id}/modules/quality/qc_result"
    payload = {
        "schema_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "plant_id": plant_id,
        "asset_id": machine_code,
        "device_timestamp": datetime.now(UTC).isoformat(),
        "payload_type": "qc_result",
        "payload": {
            "unit_id": unit_id,
            "machine_code": machine_code,
            "outcome": outcome,
            "probability": round(probability, 3),
            "defect_type": defect_type,
            "attributed_stage": attributed_stage,
        },
    }
    return topic, payload


def build_queue_depths_payload(
    plant_id: str, queue_depths: dict[str, int]
) -> tuple[str, dict]:
    topic = f"plants/{plant_id}/modules/traceability/queue_depths"
    payload = {
        "schema_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "plant_id": plant_id,
        "device_timestamp": datetime.now(UTC).isoformat(),
        "payload_type": "queue_depths",
        "payload": queue_depths,
    }
    return topic, payload
