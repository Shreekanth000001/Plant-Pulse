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


def test_duplicate_area_code_rejected(tmp_path):
    """PlantDefinition validation must reject duplicate area_code within a plant, naming the duplicate and the plant file."""
    import copy

    data = copy.deepcopy(json.loads(PLANT_FILES[0].read_text(encoding="utf-8")))
    # Duplicate first area
    dup_area = copy.deepcopy(data["areas"][0])
    dup_area["name"] = "Duplicate Area"
    data["areas"].append(dup_area)
    dup_code = dup_area["area_code"]

    with pytest.raises(ValidationError) as exc_info:
        PlantDefinition.model_validate(data)
    assert dup_code in str(exc_info.value)

    plant_file = tmp_path / "dup_area_plant.json"
    plant_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_plants(tmp_path)
    err_msg = str(exc_info.value)
    assert "dup_area_plant.json" in err_msg
    assert dup_code in err_msg


def test_duplicate_machine_code_rejected(tmp_path):
    """PlantDefinition validation must reject duplicate machine_code within a plant, naming the duplicate and the plant file."""
    import copy

    data = copy.deepcopy(json.loads(PLANT_FILES[0].read_text(encoding="utf-8")))
    # Duplicate a machine code
    dup_machine = copy.deepcopy(data["areas"][0]["machines"][0])
    dup_code = dup_machine["machine_code"]
    data["areas"][0]["machines"].append(dup_machine)

    with pytest.raises(ValidationError) as exc_info:
        PlantDefinition.model_validate(data)
    assert dup_code in str(exc_info.value)

    plant_file = tmp_path / "dup_machine_plant.json"
    plant_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_plants(tmp_path)
    err_msg = str(exc_info.value)
    assert "dup_machine_plant.json" in err_msg
    assert dup_code in err_msg


def test_duplicate_signal_code_rejected(tmp_path):
    """PlantDefinition validation must reject duplicate signal_code within a plant, naming the duplicate and the plant file."""
    import copy

    data = copy.deepcopy(json.loads(PLANT_FILES[0].read_text(encoding="utf-8")))
    # Duplicate a signal code in machine 0
    dup_signal = copy.deepcopy(data["areas"][0]["machines"][0]["signals"][0])
    dup_code = dup_signal["signal_code"]
    data["areas"][0]["machines"][0]["signals"].append(dup_signal)

    with pytest.raises(ValidationError) as exc_info:
        PlantDefinition.model_validate(data)
    assert dup_code in str(exc_info.value)

    plant_file = tmp_path / "dup_signal_plant.json"
    plant_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_plants(tmp_path)
    err_msg = str(exc_info.value)
    assert "dup_signal_plant.json" in err_msg
    assert dup_code in err_msg
