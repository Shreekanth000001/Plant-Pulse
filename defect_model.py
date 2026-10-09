"""
Defect probability model used by QC when a unit is tested.

defect_probability = base_rate
                    + shift_change_bias(current hour)
                    + weather_bias(current storm/vibration severity)
                    + telemetry_bias(this unit's own anomaly history)
                    + random noise

Weather is a placeholder constant for now (see WEATHER_INTENSITY) —
real live weather data is a planned follow-up layer, not built yet.
Keeping it as an explicit, separately-named input now means wiring in
a real API later only touches this one function, nothing downstream.
"""

import random

BASE_DEFECT_RATE = 0.04

# Hours (24h, local time) where a shift change happens — defect rate
# ticks up slightly around handoffs, per the manufacturing pattern we
# discussed (new crew, warm-up, handoff gaps).
SHIFT_CHANGE_HOURS = {6, 14, 22}
SHIFT_CHANGE_BIAS = 0.04

# Placeholder — 0 (calm) to 10 (severe storm). TODO: replace with a
# real call to a weather API (e.g. Open-Meteo), keyed by facility location.
WEATHER_INTENSITY = 0.0
WEATHER_BIAS_PER_UNIT = 0.01

TELEMETRY_BIAS_PER_ANOMALY_SCORE = 0.015


def _shift_change_bias(current_hour: int) -> float:
    return SHIFT_CHANGE_BIAS if current_hour in SHIFT_CHANGE_HOURS else 0.0


def _weather_bias() -> float:
    return WEATHER_INTENSITY * WEATHER_BIAS_PER_UNIT


def _telemetry_bias(unit) -> float:
    """Sum of every stage's anomaly_score for this unit — a unit that
    passed through machines running far from their setpoints accumulates
    a higher bias. This is what makes the final verdict depend on the
    unit's OWN journey, not just the time it happened to arrive at QC."""
    total_anomaly = sum(stage["anomaly_score"] for stage in unit.history)
    return total_anomaly * TELEMETRY_BIAS_PER_ANOMALY_SCORE


def compute_defect_probability(unit, current_hour: int) -> float:
    probability = (
        BASE_DEFECT_RATE
        + _shift_change_bias(current_hour)
        + _weather_bias()
        + _telemetry_bias(unit)
    )
    return min(probability, 0.95)  # never force a guaranteed defect


def pick_defect_type(unit) -> str:
    """Attribute the defect to whichever stage had the worst anomaly
    score — a simple, explainable heuristic, not a real causal claim."""
    worst_stage = max(unit.history, key=lambda stage: stage["anomaly_score"])
    # defect_types isn't stored on the stage record itself; the caller
    # (QCStation) passes in the lookup since it has access to config.
    return worst_stage["sub_facility"]


def decide_outcome(unit, current_hour: int) -> tuple[str, float]:
    """Returns ("pass" | "fail", the probability used), so the caller
    can log/inspect it even when the unit passes."""
    probability = compute_defect_probability(unit, current_hour)
    outcome = "fail" if random.random() < probability else "pass"
    return outcome, probability