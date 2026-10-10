"""
Standalone simulator for the full line: Housing -> Casting -> Assembly
-> QC, with real Units flowing through real queues between stages.
No MQTT, no backend yet — prints generated readings so the data can be
sanity-checked before any networking is introduced.

Machines are queue-gated: Housing always has "raw material" and can
always start a new unit, but Casting/Assembly/QC can only start work if
a unit is actually waiting in their input queue. If not, they sit idle
and starved — this is what makes bottlenecks visible instead of fake.

QC pulls from the "qc" queue, tests each unit using the defect model
(defect_model.py), and sets unit.status to "passed" or "failed" based
on that unit's full journey — not just a coin flip.

Run: python simulator.py
"""

import random
import time

from config import FACILITY
from defect_model import decide_outcome, pick_defect_type
from units import Unit

TICK_SECONDS = 2
STAGE_ORDER = ["housing", "casting", "assembly", "qc"]

# sub_facility stage_type -> list of defect types that stage can cause.
# Used by QC to pick a specific defect_type once it's decided a unit failed.
DEFECT_TYPES_BY_STAGE = {
    sf["stage_type"]: sf["machines"][0]["defect_types"]
    for sf in FACILITY["sub_facilities"]
    if sf["stage_type"] != "qc"
}


class MachineSim:
    """Represents ONE machine, of any sub-facility type. Field names for
    its readings (temperature, torque, viscosity...) are discovered
    generically from config, same as before. New in this version: each
    machine pulls a Unit from its input_queue to start a cycle (or
    creates one, if it's a Housing machine with no input queue), and
    pushes the finished Unit into output_queue when done."""

    def __init__(self, machine_id, name, sub_facility, readings, phases,
                 vibration_fault_threshold, input_queue, output_queue):
        self.machine_id = machine_id
        self.name = name
        self.sub_facility = sub_facility
        self.readings = readings
        self.vibration_fault_threshold = vibration_fault_threshold

        self.input_queue = input_queue    # None for Housing (infinite raw material)
        self.output_queue = output_queue  # where a finished unit goes next

        self.phases = phases
        self.phase_index = 0
        self.phase_elapsed = 0.0
        self.phase_duration = self._roll_phase_duration()

        self.machine_state = "IDLE"       # IDLE / RUNNING / FAULT
        self.starved = False              # True = idle because no input unit available
        self.vibration = 0.2
        self.vibration_wear_level = 0.0
        self.good_count = 0
        self.reject_count = 0

        self.current_unit: Unit | None = None
        self._cycle_started_at: float | None = None
        self._last_stage_event: dict | None = None  # set for exactly one tick when a cycle completes

    @property
    def phase(self) -> str:
        return self.phases[self.phase_index]

    def _roll_phase_duration(self) -> float:
        cycle_time = max(random.gauss(75.0, 4.0), 10.0)
        return cycle_time / len(self.phases)

    def _try_start_cycle(self) -> bool:
        """Attempt to claim a unit and leave IDLE. Returns False (stays
        idle, starved) if there's no input available."""
        if self.input_queue is None:
            self.current_unit = Unit()  # Housing: always has raw material
        else:
            if not self.input_queue:
                self.starved = True
                return False
            self.current_unit = self.input_queue.pop(0)

        self.starved = False
        self._cycle_started_at = time.time()
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
        # Still the placeholder quality check — vibration-linked only.
        # The real defect model (weather/shift/full unit history) comes
        # once QC itself is simulated and can read unit.history.
        defect_chance = 0.03 + max(0.0, (self.vibration - 4.0) * 0.03)
        outcome = "flagged" if random.random() < defect_chance else "ok"

        if outcome == "flagged":
            self.reject_count += 1
        else:
            self.good_count += 1

        unit = self.current_unit
        snapshot, anomaly_score = self._snapshot_readings()
        exited_at = time.time()
        unit.record_stage(
            sub_facility=self.sub_facility,
            machine_id=self.machine_id,
            entered_at=self._cycle_started_at,
            exited_at=exited_at,
            readings=snapshot,
            outcome=outcome,
            anomaly_score=anomaly_score,
        )

        # Exposed for exactly this one tick so mqtt_publisher can publish
        # it — otherwise this stage's contribution to the unit's history
        # never leaves this process.
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
        """Returns (actual readings, anomaly_score). anomaly_score is how
        many standard deviations away from setpoint this machine's
        readings were, summed across all its fields — this is what lets
        QC later ask 'was anything unusual while this unit was here?'
        without needing to know what 'torque' or 'viscosity' even mean."""
        snapshot = {}
        anomaly_score = 0.0
        for name, (setpoint, std) in self.readings.items():
            actual = random.gauss(setpoint, std)
            snapshot[name] = round(actual, 2)
            if std > 0:
                anomaly_score += abs(actual - setpoint) / std
        return snapshot, anomaly_score

    def _update_vibration(self) -> None:
        if self.vibration < 10:
            self.vibration += random.uniform(0, 0.1)
        self.vibration_wear_level += self.vibration * 0.01

        if self.vibration > self.vibration_fault_threshold:
            self.machine_state = "FAULT"

    def tick(self) -> dict:
        # KNOWN LIMITATION: once a machine hits FAULT, it stays FAULT
        # forever (no repair mechanic yet), and any unit it was mid-cycle
        # on is permanently stranded — never pushed downstream, never
        # marked scrapped. Fine for v1; worth a repair/scrap pass later.
        self._last_stage_event = None  # clear any event from a PREVIOUS tick first

        if self.machine_state != "FAULT":
            if self.phase == "IDLE":
                started = self._try_start_cycle()
                self.machine_state = "RUNNING" if started else "IDLE"
            else:
                self.machine_state = "RUNNING"
                self._update_vibration()
                self.phase_elapsed += TICK_SECONDS
                if self.phase_elapsed >= self.phase_duration:
                    self._advance_phase()  # may set self._last_stage_event, below

        reading = {
            "stage_event": self._last_stage_event,  # dict if a cycle just completed this tick, else None
            "machine_id": self.machine_id,
            "name": self.name,
            "machine_state": self.machine_state,
            "phase": self.phase,
            "starved": self.starved,
            "current_unit": self.current_unit.unit_id if self.current_unit else None,
            "vibration": round(self.vibration, 2),
            "vibration_wear_level": round(self.vibration_wear_level, 3),
            "good_count": self.good_count,
            "reject_count": self.reject_count,
        }

        for field_name, (setpoint, std) in self.readings.items():
            actual = random.gauss(setpoint, std)
            reading[f"{field_name}_setpoint"] = setpoint
            reading[f"{field_name}_actual"] = round(actual, 2)

        return reading


class QCStation:
    """The single testing machine. Behaves very differently from
    MachineSim: no phases/vibration/wear — it just pulls a unit from its
    input queue, 'tests' it for a rolled duration, then decides pass/fail
    using the defect model, which reads the unit's FULL history."""

    def __init__(self, machine_id, name, input_queue, test_duration_mean, test_duration_std):
        self.machine_id = machine_id
        self.name = name
        self.input_queue = input_queue

        self.test_duration_mean = test_duration_mean
        self.test_duration_std = test_duration_std

        self.machine_state = "IDLE"  # IDLE / TESTING
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
        self._test_duration = max(random.gauss(self.test_duration_mean, self.test_duration_std), 5.0)
        return True

    def _finish_test(self) -> dict:
        unit = self.current_unit
        current_hour = time.localtime().tm_hour
        outcome, probability = decide_outcome(unit, current_hour)

        result = {"unit_id": unit.unit_id, "outcome": outcome, "probability": round(probability, 3)}

        if outcome == "fail":
            failed_stage = pick_defect_type(unit)  # returns sub_facility name
            defect_type = random.choice(DEFECT_TYPES_BY_STAGE[failed_stage])
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
        else:  # TESTING
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
        }


def _extract_readings(machine_config: dict) -> dict:
    readings = {}
    for key, value in machine_config.items():
        if key.endswith("_setpoint"):
            base_name = key[: -len("_setpoint")]
            std_key = f"{base_name}_normal_std"
            readings[base_name] = (value, machine_config[std_key])
    return readings


class Line:
    """Owns the queues between stages and all the machines. This is the
    orchestrator — MachineSim objects don't know about each other, only
    about the queue lists they were handed."""

    def __init__(self):
        # One queue per stage *except* housing (which has no input queue —
        # infinite raw material). Units sit in "qc" queue waiting, since
        # QC isn't simulated yet.
        self.queues: dict[str, list[Unit]] = {
            stage: [] for stage in STAGE_ORDER if stage != "housing"
        }
        self.machines: list[MachineSim] = []
        self.qc_stations: list[QCStation] = []
        self._build_machines()

    def _build_machines(self) -> None:
        sub_facilities_by_type = {sf["stage_type"]: sf for sf in FACILITY["sub_facilities"]}

        for stage_type in STAGE_ORDER:
            sf = sub_facilities_by_type[stage_type]

            if stage_type == "qc":
                for m in sf["machines"]:
                    self.qc_stations.append(
                        QCStation(
                            machine_id=m["machine_id"],
                            name=m["name"],
                            input_queue=self.queues["qc"],
                            test_duration_mean=m["test_duration_mean"],
                            test_duration_std=m["test_duration_std"],
                        )
                    )
                continue

            stage_pos = STAGE_ORDER.index(stage_type)
            next_stage = STAGE_ORDER[stage_pos + 1]

            input_queue = None if stage_type == "housing" else self.queues[stage_type]
            output_queue = self.queues[next_stage]

            for m in sf["machines"]:
                self.machines.append(
                    MachineSim(
                        machine_id=m["machine_id"],
                        name=m["name"],
                        sub_facility=stage_type,
                        readings=_extract_readings(m),
                        phases=sf["phases"],
                        vibration_fault_threshold=m["vibration_fault_threshold"],
                        input_queue=input_queue,
                        output_queue=output_queue,
                    )
                )

    def tick(self) -> list[dict]:
        readings = [m.tick() for m in self.machines]
        readings += [q.tick() for q in self.qc_stations]
        return readings

    def queue_depths(self) -> dict:
        return {stage: len(q) for stage, q in self.queues.items()}


def main() -> None:
    line = Line()
    total = len(line.machines) + len(line.qc_stations)
    print(f"Simulating {total} machines across the full line (Housing -> Casting -> Assembly -> QC).")
    print("Ctrl+C to stop.\n")

    tick_count = 0
    try:
        while True:
            for reading in line.tick():
                if reading.get("last_result"):  # QC just finished testing a unit
                    print(">>>", reading["last_result"])
                else:
                    print(reading)

            tick_count += 1
            if tick_count % 10 == 0:
                print(f"\n--- queue depths: {line.queue_depths()} ---\n")

            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()