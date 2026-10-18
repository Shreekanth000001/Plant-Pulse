import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


class SignalDefinition(BaseModel):
    signal_code: str = Field(..., pattern=r"^[a-z0-9_]{2,64}$")
    name: str
    unit: str = ""
    data_type: Literal["float", "int", "bool", "string"] = "float"
    is_setpoint: bool = False
    setpoint_signal_code: str | None = None
    normal_min: float | None = None
    normal_max: float | None = None
    warn_min: float | None = None
    warn_max: float | None = None
    alarm_min: float | None = None
    alarm_max: float | None = None
    display_order: int = 0


class MachineDefinition(BaseModel):
    machine_code: str = Field(..., pattern=r"^[a-z0-9_]{2,64}$")
    name: str
    machine_type: str = "standard"
    display_order: int = 0
    signals: list[SignalDefinition]

    @model_validator(mode="after")
    def validate_setpoints_exist(self) -> "MachineDefinition":
        codes = {s.signal_code for s in self.signals}
        for s in self.signals:
            if s.setpoint_signal_code and s.setpoint_signal_code not in codes:
                raise ValueError(
                    f"Machine '{self.machine_code}': setpoint_signal_code "
                    f"'{s.setpoint_signal_code}' references non-existent signal."
                )
        return self


class AreaDefinition(BaseModel):
    area_code: str = Field(..., pattern=r"^[a-z0-9_]{2,64}$")
    name: str
    display_order: int = 0
    machines: list[MachineDefinition]


class MQTTCredential(BaseModel):
    username: str
    password: str
    client_id: str


class PlantDefinition(BaseModel):
    plant_id: str = Field(..., pattern=r"^[a-z0-9_]{3,64}$")
    name: str
    timezone: str = "UTC"
    viewer_token: str | None = None  # None indicates public demo plant
    enabled_modules: list[
        Literal["core", "alarms", "product_traceability", "quality_inspection"]
    ] = ["core", "alarms"]
    mqtt_credentials: list[MQTTCredential]
    areas: list[AreaDefinition]


def load_plants(directory: Path) -> dict[str, PlantDefinition]:
    plants: dict[str, PlantDefinition] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            plant = PlantDefinition.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"Invalid plant definition {path.name}: {exc}") from exc
        if plant.plant_id in plants:
            raise ValueError(f"Duplicate plant_id '{plant.plant_id}' in {path.name}")
        plants[plant.plant_id] = plant
    return plants
