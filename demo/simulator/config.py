"""
Facility configuration — plain data, no logic.

This describes WHAT exists (facility -> sub-facilities -> machines) and
their normal operating characteristics. The simulator (next step) will
read this and generate telemetry that fluctuates around these values.

Starting with just Housing to validate the shape before templating out
Membrane Casting, Assembly, and QC.
"""

# Phases a Housing (molding) machine cycles through to produce one unit.
# Kept to 4 instead of the full real-world 8 for v1 simplicity.
HOUSING_PHASES = ["IDLE", "FORMING", "COOLING", "EJECTION"]

# Possible fault codes a Housing machine can raise. Used when
# machine_state == "FAULT". None of these are wired to logic yet —
# that comes in the simulator step.
HOUSING_FAULT_CODES = ["MOLD_TEMP_HIGH", "PRESSURE_LOSS", "JAM"]

# Defect types this sub-facility's QC check can attribute to a unit,
# if that unit fails and the failure is traced back to Housing.
HOUSING_DEFECT_TYPES = ["CRACK", "DIMENSIONAL_DEVIATION"]

# Membrane Casting — a different physical process (extrusion/casting,
# not molding), so its own phases/fault codes/defect types.
CASTING_PHASES = ["IDLE", "FORMING", "COOLING", "EJECTION"]
CASTING_FAULT_CODES = ["CAST_TEMP_HIGH", "PRESSURE_LOSS", "JAM"]
CASTING_DEFECT_TYPES = ["PORE_INCONSISTENCY", "THICKNESS_DEVIATION"]

# Assembly — joins housing + membrane into a finished unit.
ASSEMBLY_PHASES = ["IDLE", "ALIGNING", "JOINING", "SEALING"]
ASSEMBLY_FAULT_CODES = ["TORQUE_OUT_OF_RANGE", "SEAL_PRESSURE_LOW", "JAM"]
ASSEMBLY_DEFECT_TYPES = ["MISALIGNMENT", "SEAL_FAILURE"]

# QC — the single testing machine. No "production" phases; it just
# tests whatever unit arrives and records an outcome.
QC_PHASES = ["IDLE", "TESTING"]
QC_FAULT_CODES = ["SENSOR_ERROR", "CALIBRATION_DRIFT"]
# QC doesn't cause defects itself — its defect_types field lists every
# defect type it's capable of detecting, across all upstream stages.
QC_DETECTABLE_DEFECT_TYPES = (
    HOUSING_DEFECT_TYPES + CASTING_DEFECT_TYPES + ASSEMBLY_DEFECT_TYPES
)


def make_housing_machine(machine_id: str, name: str) -> dict:
    """Template for one Housing/molding machine. All machines in this
    sub-facility share the same field shape; only machine_id/name differ.
    (Per-machine drift/wear will be added in the simulator, not here.)"""
    return {
        "machine_id": machine_id,
        "name": name,
        "sub_facility": "housing",
        # --- normal operating ranges (used by simulator to generate values) ---
        "mold_temperature_setpoint": 65.0,  # °C, the target
        "mold_temperature_normal_std": 1.5,  # how much "actual" naturally wanders around setpoint
        "vibration_normal": 2.0,  # mm/s, healthy baseline
        "vibration_fault_threshold": 7.0,  # mm/s, above this -> FAULT
        "cycle_time_mean": 75.0,  # seconds, average time per unit
        "cycle_time_std": 4.0,  # natural variance per cycle
        "fault_codes": HOUSING_FAULT_CODES,
        "defect_types": HOUSING_DEFECT_TYPES,
    }


def make_casting_machine(machine_id: str, name: str) -> dict:
    """Template for one Membrane Casting machine."""
    return {
        "machine_id": machine_id,
        "name": name,
        "sub_facility": "casting",
        "extrusion_temp_setpoint": 65.0,  # °C, target
        "extrusion_temp_normal_std": 1.5,
        "viscosity_setpoint": 34.0,
        "viscosity_normal_std": 2.0,
        "vibration_normal": 2.0,
        "vibration_fault_threshold": 5.0,
        "cycle_time_mean": 120.0,
        "cycle_time_std": 10.0,
        "fault_codes": CASTING_FAULT_CODES,
        "defect_types": CASTING_DEFECT_TYPES,
    }


def make_assembly_machine(machine_id: str, name: str) -> dict:
    """Template for one Assembly machine — joins housing + membrane."""
    return {
        "machine_id": machine_id,
        "name": name,
        "sub_facility": "assembly",
        "torque_setpoint": 45.0,
        "torque_normal_std": 3.0,
        "seal_pressure_setpoint": 6.0,
        "seal_pressure_normal_std": 0.4,
        "vibration_normal": 1.5,
        "vibration_fault_threshold": 6.0,
        "cycle_time_mean": 50.0,
        "cycle_time_std": 5.0,
        "fault_codes": ASSEMBLY_FAULT_CODES,
        "defect_types": ASSEMBLY_DEFECT_TYPES,
    }


def make_qc_machine(machine_id: str, name: str) -> dict:
    """Template for QC test station."""
    return {
        "machine_id": machine_id,
        "name": name,
        "sub_facility": "qc",
        "test_duration_mean": 20.0,
        "test_duration_std": 3.0,
        "fault_codes": QC_FAULT_CODES,
        "defect_types": QC_DETECTABLE_DEFECT_TYPES,
    }


FACILITY = {
    "facility_id": "plant_demo_membrane",
    "name": "Membrane Manufacturing Facility 01",
    "sub_facilities": [
        {
            "sub_facility_id": "sf_housing",
            "name": "Housing Sub-Facility",
            "stage_type": "housing",
            "phases": HOUSING_PHASES,
            "machines": [
                make_housing_machine("hm_01", "Housing Molder 1"),
                make_housing_machine("hm_02", "Housing Molder 2"),
            ],
        },
        {
            "sub_facility_id": "sf_casting",
            "name": "Membrane Casting Line",
            "stage_type": "casting",
            "phases": CASTING_PHASES,
            "machines": [
                make_casting_machine("cs_01", "Casting Machine 1"),
                make_casting_machine("cs_02", "Casting Machine 2"),
            ],
        },
        {
            "sub_facility_id": "sf_assembly",
            "name": "Robotic Assembly",
            "stage_type": "assembly",
            "phases": ASSEMBLY_PHASES,
            "machines": [
                make_assembly_machine("am_01", "Assembly Station 1"),
                make_assembly_machine("am_02", "Assembly Station 2"),
                make_assembly_machine("am_03", "Assembly Station 3"),
                make_assembly_machine("am_04", "Assembly Station 4"),
            ],
        },
        {
            "sub_facility_id": "sf_qc",
            "name": "Quality Testing Station",
            "stage_type": "qc",
            "phases": QC_PHASES,
            "machines": [
                make_qc_machine("qc_01", "QC Test Station 1"),
                make_qc_machine("qc_02", "QC Test Station 2"),
                make_qc_machine("qc_03", "QC Test Station 3"),
            ],
        },
    ],
}
