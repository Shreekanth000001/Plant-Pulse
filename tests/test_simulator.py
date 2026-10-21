import random

import pytest

from demo.simulator import simulator
from demo.simulator.config import FACILITY
from demo.simulator.units import Unit

CYCLES = 50
TOLERANCE = 0.15  # deviation allowed from the expected value


def expected_cycle_time(machine_id):  # search FACILITY for the machine

    for sub_facility in FACILITY["sub_facilities"]:
        for machine in sub_facility["machines"]:
            if machine["machine_id"] == machine_id:
                return machine["cycle_time_mean"]

    raise KeyError(machine_id)


def measure_average_cycle_time(machine_id):  # seed, build Line, pick machine,
    headroom = 1.2
    ticks = int(
        CYCLES * (expected_cycle_time(machine_id) / simulator.TICK_SECONDS) * headroom
    )

    print(f"ticks - {ticks}")

    random.seed(42)

    units = [Unit() for _ in range(2 * CYCLES)]

    line = simulator.Line()
    m = next(x for x in line.machines if x.machine_id == machine_id)

    if m.input_queue is not None:  # Housing's queue is None: nothing feeds it
        m.input_queue.extend(units)  # append the whole list to the machine's queue

    m.vibration_fault_threshold = float("inf")
    for _ in range(ticks):
        m.tick()
    print(m.phase, m.machine_state, m.good_count, m.reject_count)

    completed = m.good_count + m.reject_count

    assert completed > 0, f"{machine_id} failed with completed - {completed}"

    average_cycle_time = (ticks * simulator.TICK_SECONDS) / completed

    return average_cycle_time


@pytest.mark.parametrize("machine_id", ["hm_01", "cs_01", "am_01"])
def test_average_cycle_time_matches_config(machine_id):

    expected = expected_cycle_time(machine_id)
    measured = measure_average_cycle_time(machine_id)
    print(expected, measured)

    assert measured == pytest.approx(expected, rel=TOLERANCE)
