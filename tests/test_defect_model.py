from types import SimpleNamespace

import pytest

from demo.simulator.defect_model import (
    SHIFT_CHANGE_BIAS,
    compute_defect_probability,
)


def make_unit(anomaly_scores):
    return SimpleNamespace(history=[{"anomaly_score": s} for s in anomaly_scores])


def test_probability_never_exceeds_cap():
    unit = make_unit([50.0, 50.0, 50.0])

    result = compute_defect_probability(unit, current_hour=6)

    assert result <= 0.95
    assert result == 0.95


def test_shift_change_bias():

    unit = make_unit([0])

    shift_value = compute_defect_probability(unit, current_hour=6)
    quiet_value = compute_defect_probability(unit, current_hour=12)

    result = shift_value - quiet_value

    assert result == pytest.approx(SHIFT_CHANGE_BIAS)


def test_unit_anomaly_probability():

    clean_unit = make_unit([0.5, 1.0, 0.5])
    low_anomoly_result = compute_defect_probability(clean_unit, current_hour=5)

    drifting_unit = make_unit([4.0, 5.0, 3.0])
    high_anomoly_result = compute_defect_probability(drifting_unit, current_hour=5)

    assert low_anomoly_result < high_anomoly_result
