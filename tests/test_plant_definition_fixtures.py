from pathlib import Path

import pytest
from pydantic import ValidationError

from plant_definitions import PlantDefinition

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "plants"


def test_valid_minimal_fixture_passes_validation():
    fixture_path = FIXTURES_DIR / "valid_minimal.json"
    content = fixture_path.read_text(encoding="utf-8")
    plant = PlantDefinition.model_validate_json(content)
    assert plant.plant_id == "plant_minimal_fixture"
    assert len(plant.areas) == 1
    assert plant.areas[0].machines[0].signals[0].signal_code == "temp_actual"


def test_invalid_duplicate_signals_fixture_rejected():
    fixture_path = FIXTURES_DIR / "invalid_duplicate_signals.json"
    content = fixture_path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate signal_code 'pressure'"):
        PlantDefinition.model_validate_json(content)


def test_invalid_pattern_fixture_rejected():
    fixture_path = FIXTURES_DIR / "invalid_pattern.json"
    content = fixture_path.read_text(encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        PlantDefinition.model_validate_json(content)
    assert any("pattern" in str(err) for err in exc_info.value.errors())


def test_threshold_order_violation_fixture_accepted_by_backend():
    """Confirms PlantDefinition schema does NOT reject inverted min/max thresholds.

    Because the backend accepts it without error, any client threshold order
    enforcement must remain purely advisory and not block submission.
    """
    fixture_path = FIXTURES_DIR / "threshold_order_violation.json"
    content = fixture_path.read_text(encoding="utf-8")
    plant = PlantDefinition.model_validate_json(content)
    assert plant.plant_id == "plant_threshold_violation"
    sig = plant.areas[0].machines[0].signals[0]
    # Inverted min/max values are accepted by backend schema
    assert sig.normal_min == 50.0
    assert sig.normal_max == 20.0
    assert sig.warn_min == 60.0
    assert sig.warn_max == 10.0
