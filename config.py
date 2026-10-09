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
        "mold_temperature_setpoint": 65.0,       # °C, the target
        "mold_temperature_normal_std": 1.5,      # how much "actual" naturally wanders around setpoint

        "vibration_normal": 2.0,                 # mm/s, healthy baseline
        "vibration_fault_threshold": 7.0,         # mm/s, above this -> FAULT

        "cycle_time_mean": 75.0,                 # seconds, average time per unit
        "cycle_time_std": 4.0,                   # natural variance per cycle

        "fault_codes": HOUSING_FAULT_CODES,
        "defect_types": HOUSING_DEFECT_TYPES,
    }


def make_casting_machine(machine_id: str, name: str) -> dict:
    """Template for one Membrane Casting machine. Different process from
    Housing (extrusion/casting, not molding), so different fields — but
    keeps vibration/wear so MachineSim can treat every machine the same
    way regardless of sub-facility."""
    return {
        "machine_id": machine_id,
        "name": name,
        "sub_facility": "casting",

        "extrusion_temperature_setpoint": 65.0,   # °C, the target
        "extrusion_temperature_normal_std": 1.5,  # natural wobble around setpoint

        "extrusion_speed_setpoint": 20.0,         # mm/s, the target
        "extrusion_speed_normal_std": 1.0,        # natural wobble around setpoint

        "viscosity_setpoint": 34.0,               # arbitrary unit, the target
        "viscosity_normal_std": 2.0,              # natural wobble around setpoint

        "humidity_setpoint": 12.0,                # %, the target
        "humidity_normal_std": 0.5,               # natural wobble around setpoint

        "vibration_normal": 2.0,                  # mm/s, healthy baseline
        "vibration_fault_threshold": 7.0,         # mm/s, above this -> FAULT

        "cycle_time_mean": 120.0,                 # seconds, average time per unit
        "cycle_time_std": 10.0,                   # natural variance per cycle

        "fault_codes": CASTING_FAULT_CODES,
        "defect_types": CASTING_DEFECT_TYPES,
    }


def make_assembly_machine(machine_id: str, name: str) -> dict:
    """Template for one Assembly machine — joins housing + membrane."""
    return {
        "machine_id": machine_id,
        "name": name,
        "sub_facility": "assembly",

        "torque_setpoint": 45.0,          # N*m, the target
        "torque_normal_std": 3.0,         # natural wobble around setpoint

        "seal_pressure_setpoint": 6.0,    # bar, the target
        "seal_pressure_normal_std": 0.4,  # natural wobble around setpoint

        "vibration_normal": 1.5,          # mm/s, healthy baseline
        "vibration_fault_threshold": 6.0, # mm/s, above this -> FAULT

        "cycle_time_mean": 50.0,          # seconds, average time per unit
        "cycle_time_std": 5.0,            # natural variance per cycle

        "fault_codes": ASSEMBLY_FAULT_CODES,
        "defect_types": ASSEMBLY_DEFECT_TYPES,
    }


def make_qc_machine(machine_id: str, name: str) -> dict:
    """Template for the single QC/testing machine. It doesn't produce a
    physical unit — it tests one that already exists and records pass/fail.
    No vibration/wear modeled; it's a measurement station, not a forming
    machine, so degradation isn't the relevant signal here."""
    return {
        "machine_id": machine_id,
        "name": name,
        "sub_facility": "qc",

        "test_duration_mean": 20.0,       # seconds, average time per test
        "test_duration_std": 3.0,         # natural variance per test

        "fault_codes": QC_FAULT_CODES,
        "defect_types": QC_DETECTABLE_DEFECT_TYPES,
    }


FACILITY = {
    "facility_id": "fac_1",
    "name": "Membrane Manufacturing Plant 1",
    "sub_facilities": [
        {
            "sub_facility_id": "sf_housing",
            "name": "Housing",
            "stage_type": "housing",
            "phases": HOUSING_PHASES,
            "machines": [
                make_housing_machine("hm_01", "Housing Molder 1"),
                make_housing_machine("hm_02", "Housing Molder 2"),
                make_housing_machine("hm_03", "Housing Molder 3"),
                make_housing_machine("hm_04", "Housing Molder 4"),
            ],
        },
        {
            "sub_facility_id": "sf_casting",
            "name": "Membrane Casting",
            "stage_type": "casting",
            "phases": CASTING_PHASES,
            "machines": [
                make_casting_machine("cs_01", "Casting Machine 1"),
                make_casting_machine("cs_02", "Casting Machine 2"),
                make_casting_machine("cs_03", "Casting Machine 3"),
            ],
        },
        {
            "sub_facility_id": "sf_assembly",
            "name": "Assembly",
            "stage_type": "assembly",
            "phases": ASSEMBLY_PHASES,
            "machines": [
                make_assembly_machine("am_01", "Assembly Station 1"),
                make_assembly_machine("am_02", "Assembly Station 2"),
                make_assembly_machine("am_03", "Assembly Station 3"),
            ],
        },
        {
            "sub_facility_id": "sf_qc",
            "name": "Testing / QC",
            "stage_type": "qc",
            "phases": QC_PHASES,
            "machines": [
                make_qc_machine("qc_01", "QC Test Station"),
            ],
        },
    ],
}