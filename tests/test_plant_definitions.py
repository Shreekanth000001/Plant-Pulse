import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from plant_definitions import PlantDefinition, load_plants

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"
PLANT_FILES = sorted(PLANTS_DIR.glob("*.json"))


def test_plant_files_exist():
    assert len(PLANT_FILES) >= 2


@pytest.mark.parametrize("path", PLANT_FILES, ids=lambda p: p.name)
def test_reference_plant_is_valid(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    PlantDefinition.model_validate(data)


def test_missing_setpoint_signal_is_rejected():
    data = json.loads(PLANT_FILES[0].read_text(encoding="utf-8"))
    signal = data["areas"][0]["machines"][0]["signals"][0]
    signal["setpoint_signal_code"] = "does_not_exist"

    with pytest.raises(ValidationError):
        PlantDefinition.model_validate(data)


def test_load_plants_returns_both():

    plants = load_plants(PLANTS_DIR)

    assert len(plants) == len(PLANT_FILES)


def test_bad_file_error_names_the_file(tmp_path):

    (tmp_path / "bad.json").write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_plants(tmp_path)

    assert "bad.json" in str(exc_info.value)
