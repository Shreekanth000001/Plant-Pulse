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
    def validate_signals_and_setpoints(self) -> "MachineDefinition":
        seen_signals: set[str] = set()
        for s in self.signals:
            if s.signal_code in seen_signals:
                raise ValueError(
                    f"Machine '{self.machine_code}': duplicate signal_code '{s.signal_code}'"
                )
            seen_signals.add(s.signal_code)

        codes = seen_signals
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

    @model_validator(mode="after")
    def validate_unique_machines(self) -> "AreaDefinition":
        seen: set[str] = set()
        for m in self.machines:
            if m.machine_code in seen:
                raise ValueError(
                    f"Area '{self.area_code}': duplicate machine_code '{m.machine_code}'"
                )
            seen.add(m.machine_code)
        return self


class MQTTCredential(BaseModel):
    username: str
    password: str
    client_id: str


class PlantSummary(BaseModel):
    plant_id: str = Field(..., pattern=r"^[a-z0-9_]{3,64}$")
    name: str
    timezone: str = "UTC"
    has_viewer_token: bool = False
    enabled_modules: list[
        Literal["core", "alarms", "product_traceability", "quality_inspection"]
    ] = ["core", "alarms"]


class PublicPlantDefinition(PlantSummary):
    areas: list[AreaDefinition]

    @model_validator(mode="after")
    def validate_unique_codes(self) -> "PublicPlantDefinition":
        seen_areas: set[str] = set()
        seen_machines: set[str] = set()
        for area in self.areas:
            if area.area_code in seen_areas:
                raise ValueError(
                    f"Plant '{self.plant_id}': duplicate area_code '{area.area_code}'"
                )
            seen_areas.add(area.area_code)

            for m in area.machines:
                if m.machine_code in seen_machines:
                    raise ValueError(
                        f"Plant '{self.plant_id}': duplicate machine_code '{m.machine_code}'"
                    )
                seen_machines.add(m.machine_code)
        return self


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

    @model_validator(mode="after")
    def validate_unique_codes(self) -> "PlantDefinition":
        seen_areas: set[str] = set()
        seen_machines: set[str] = set()
        for area in self.areas:
            if area.area_code in seen_areas:
                raise ValueError(
                    f"Plant '{self.plant_id}': duplicate area_code '{area.area_code}'"
                )
            seen_areas.add(area.area_code)

            for m in area.machines:
                if m.machine_code in seen_machines:
                    raise ValueError(
                        f"Plant '{self.plant_id}': duplicate machine_code '{m.machine_code}'"
                    )
                seen_machines.add(m.machine_code)
        return self

    def to_public(self) -> PublicPlantDefinition:
        dump = self.model_dump()
        dump["has_viewer_token"] = bool(self.viewer_token)
        return PublicPlantDefinition.model_validate(dump)

    def to_summary(self) -> PlantSummary:
        dump = self.model_dump()
        dump["has_viewer_token"] = bool(self.viewer_token)
        return PlantSummary.model_validate(dump)


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
