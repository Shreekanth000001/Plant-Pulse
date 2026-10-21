import json
from pathlib import Path
from typing import Any, Literal

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
    viewer_token_hash: str | None = None
    enabled_modules: list[
        Literal["core", "alarms", "product_traceability", "quality_inspection"]
    ] = ["core", "alarms"]
    mqtt_credentials: list[MQTTCredential] = Field(default_factory=list)
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
        dump["has_viewer_token"] = bool(self.viewer_token or self.viewer_token_hash)
        return PublicPlantDefinition.model_validate(dump)

    def to_summary(self) -> PlantSummary:
        dump = self.model_dump()
        dump["has_viewer_token"] = bool(self.viewer_token or self.viewer_token_hash)
        return PlantSummary.model_validate(dump)


class AdminPlantSummary(BaseModel):
    plant_id: str = Field(..., pattern=r"^[a-z0-9_]{3,64}$")
    name: str
    timezone: str = "UTC"
    has_viewer_token: bool = False


class AdminPlantDetail(BaseModel):
    plant_id: str = Field(..., pattern=r"^[a-z0-9_]{3,64}$")
    name: str
    timezone: str = "UTC"
    has_viewer_token: bool = False
    device_usernames: list[str] = Field(default_factory=list)
    areas: list[AreaDefinition] = Field(default_factory=list)


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


def load_plants_from_db(conn: Any) -> dict[str, PlantDefinition]:
    """Load and reconstruct all plant definitions from the platform database."""
    plants: dict[str, PlantDefinition] = {}
    original_row_factory = conn.row_factory
    import sqlite3

    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, timezone, viewer_token_hash FROM plants ORDER BY id;"
        )
        plant_rows = cur.fetchall()

        for p_row in plant_rows:
            p_id = p_row["id"]
            cur.execute(
                "SELECT area_code, name, display_order FROM areas WHERE plant_id = ? ORDER BY display_order, area_code;",
                (p_id,),
            )
            area_rows = cur.fetchall()
            areas: list[AreaDefinition] = []
            for a_row in area_rows:
                a_code = a_row["area_code"]
                cur.execute(
                    "SELECT machine_code, name, machine_type, display_order FROM machines WHERE plant_id = ? AND area_code = ? ORDER BY display_order, machine_code;",
                    (p_id, a_code),
                )
                machine_rows = cur.fetchall()
                machines: list[MachineDefinition] = []
                for m_row in machine_rows:
                    m_code = m_row["machine_code"]
                    cur.execute(
                        """
                        SELECT signal_code, name, unit, data_type, is_setpoint, setpoint_signal_code,
                               normal_min, normal_max, warn_min, warn_max, alarm_min, alarm_max, display_order
                        FROM signals
                        WHERE plant_id = ? AND machine_code = ?
                        ORDER BY display_order, signal_code;
                        """,
                        (p_id, m_code),
                    )
                    signal_rows = cur.fetchall()
                    signals = [
                        SignalDefinition(
                            signal_code=s["signal_code"],
                            name=s["name"],
                            unit=s["unit"] or "",
                            data_type=s["data_type"],
                            is_setpoint=bool(s["is_setpoint"]),
                            setpoint_signal_code=s["setpoint_signal_code"],
                            normal_min=s["normal_min"],
                            normal_max=s["normal_max"],
                            warn_min=s["warn_min"],
                            warn_max=s["warn_max"],
                            alarm_min=s["alarm_min"],
                            alarm_max=s["alarm_max"],
                            display_order=s["display_order"],
                        )
                        for s in signal_rows
                    ]
                    machines.append(
                        MachineDefinition(
                            machine_code=m_code,
                            name=m_row["name"],
                            machine_type=m_row["machine_type"],
                            display_order=m_row["display_order"],
                            signals=signals,
                        )
                    )
                areas.append(
                    AreaDefinition(
                        area_code=a_code,
                        name=a_row["name"],
                        display_order=a_row["display_order"],
                        machines=machines,
                    )
                )

            cur.execute(
                "SELECT username, client_id, password_hash FROM plant_credentials WHERE plant_id = ?;",
                (p_id,),
            )
            cred_rows = cur.fetchall()
            creds = [
                MQTTCredential(
                    username=c["username"],
                    password=c["password_hash"],
                    client_id=c["client_id"],
                )
                for c in cred_rows
            ]

            enabled_modules = (
                ["core", "alarms", "product_traceability", "quality_inspection"]
                if p_id == "plant_demo_membrane"
                else ["core", "alarms"]
            )
            plants[p_id] = PlantDefinition(
                plant_id=p_id,
                name=p_row["name"],
                timezone=p_row["timezone"],
                viewer_token=None,
                viewer_token_hash=p_row["viewer_token_hash"],
                enabled_modules=enabled_modules,
                mqtt_credentials=creds,
                areas=areas,
            )
    finally:
        conn.row_factory = original_row_factory

    return plants
