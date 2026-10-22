#!/usr/bin/env python3
"""Citrus Grove Juice Line Multi-Module Simulator.

Simulates a continuous high-throughput juice manufacturing & bottling line:
1. extractor_01   (Citrus Reamer Extractor)
2. pasteurizer_01 (HTST Flash Pasteurizer)
3. filler_01      (Rotary 24-Head Bottle Filler)
4. capper_01      (Torque Induction Capper)
5. inspector_01   (Optical Fill & Cap Inspector)

Publishes:
- Canonical machine telemetry with current_unit_id & sensor metrics
- MES stage completion events (plants/{plant}/modules/traceability/stage_event)
- End-of-line optical QC verdicts (plants/{plant}/modules/quality/qc_result)
- Inter-stage buffer counts (plants/{plant}/modules/traceability/queue_depths)
"""

import argparse
import json
import math
import os
import random
import sys
import time
import uuid
from datetime import UTC, datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt is required. Run 'pip install paho-mqtt'.", file=sys.stderr)
    sys.exit(1)

STATIONS = [
    {
        "code": "extractor_01",
        "area": "extraction_pasteurization",
        "name": "Extractor",
    },
    {
        "code": "pasteurizer_01",
        "area": "extraction_pasteurization",
        "name": "Pasteurizer",
    },
    {
        "code": "filler_01",
        "area": "bottling_capping",
        "name": "Bottle Filler",
    },
    {
        "code": "capper_01",
        "area": "bottling_capping",
        "name": "Capper",
    },
    {
        "code": "inspector_01",
        "area": "inspection_packaging",
        "name": "Vision Inspector",
    },
]


def generate_readings(station_code: str, step: int) -> dict[str, float]:
    """Generate realistic physics-based signals for each juice processing machine."""
    t = float(step)
    noise = random.uniform(-0.05, 0.05)

    if station_code == "extractor_01":
        return {
            "feed_rate_lpm": round(94.0 + math.sin(t / 4.0) * 3.5 + random.uniform(-0.5, 0.5), 1),
            "pulp_density_pct": round(10.2 + math.cos(t / 5.0) * 0.8 + random.uniform(-0.1, 0.1), 1),
            "motor_vibration_mms": round(1.20 + math.sin(t / 3.0) * 0.15 + abs(noise), 2),
        }
    elif station_code == "pasteurizer_01":
        return {
            "brix_level": round(11.8 + math.sin(t / 6.0) * 0.4 + random.uniform(-0.1, 0.1), 1),
            "pasteurization_temp_c": round(72.5 + math.cos(t / 4.0) * 1.2 + random.uniform(-0.2, 0.2), 1),
            "tube_pressure_bar": round(2.80 + math.sin(t / 5.0) * 0.15 + random.uniform(-0.03, 0.03), 2),
        }
    elif station_code == "filler_01":
        return {
            "fill_volume_ml": round(500.0 + math.sin(t / 3.0) * 2.0 + random.uniform(-0.5, 0.5), 1),
            "filling_speed_bpm": round(120.0 + math.sin(t / 5.0) * 5.0 + random.randint(-2, 2)),
            "cleanroom_pressure_pa": round(25.0 + math.cos(t / 4.0) * 1.5 + random.uniform(-0.3, 0.3), 1),
        }
    elif station_code == "capper_01":
        return {
            "capping_torque_nm": round(3.20 + math.sin(t / 4.0) * 0.25 + random.uniform(-0.05, 0.05), 2),
            "vibration_mms": round(0.85 + math.cos(t / 3.0) * 0.10 + abs(noise), 2),
        }
    elif station_code == "inspector_01":
        return {
            "reject_rate_pct": round(0.40 + math.sin(t / 7.0) * 0.15 + random.uniform(-0.05, 0.05), 2),
            "fill_height_error_mm": round(0.12 + math.cos(t / 4.0) * 0.08 + random.uniform(-0.02, 0.02), 2),
        }
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate Citrus Grove Juice Plant Line")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds (0 = infinite)")
    parser.add_argument("--password", type=str, default="E-7KfOHryRONXOJDiWKWp_Ziu_HhiC16XySNLkzUhcc", help="Device MQTT password")
    parser.add_argument("--plant-id", type=str, default="plant_citrus_grove_juice", help="Plant identifier")
    parser.add_argument("--broker-host", type=str, default=os.getenv("MQTT_HOST", "broker"), help="Broker hostname")
    parser.add_argument("--broker-port", type=int, default=int(os.getenv("MQTT_PORT", "1883")), help="Broker port")
    parser.add_argument("--rate", type=float, default=1.0, help="Cycle delay in seconds")
    args = parser.parse_args()

    plant_id = args.plant_id
    username = f"device_{plant_id}"
    password = args.password
    duration = args.duration
    cycle_delay = max(0.2, args.rate)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"sim_{plant_id}_{uuid.uuid4().hex[:6]}"
    )
    client.username_pw_set(username, password)

    print(f"Connecting to MQTT broker at {args.broker_host}:{args.broker_port} as '{username}'...")
    try:
        client.connect(args.broker_host, args.broker_port, keepalive=60)
        client.loop_start()
    except Exception as e:  # noqa: BLE001
        print(f"Failed to connect to broker: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✓ Connected to broker. Streaming juice line telemetry & serialized units for {plant_id}...")
    if duration > 0:
        print(f"Running for {duration} seconds (Ctrl+C to stop)...")
    else:
        print("Running indefinitely (Ctrl+C to stop)...")

    # Conveyor state: slots 0..4 corresponding to each station in STATIONS
    # slot holds: {"unit_id": str, "entered_at": str, "entered_step": int} or None
    line_slots: list[dict | None] = [None] * len(STATIONS)

    unit_counter = int(time.time()) % 10000
    date_prefix = datetime.now(UTC).strftime("%Y%m%d")

    good_counts = {st["code"]: 0 for st in STATIONS}
    reject_counts = {st["code"]: 0 for st in STATIONS}
    total_passed = 0
    total_failed = 0

    step = 0
    try:
        while True:
            step += 1
            now = datetime.now(UTC)
            now_iso = now.isoformat()

            # 1. Advance the conveyor line from downstream (inspector) back to upstream (extractor)
            # Check station 4 (inspector_01): completed unit exits the line
            exiting_unit = line_slots[4]
            if exiting_unit:
                # Stage event for inspector_01
                st = STATIONS[4]
                station_metrics = generate_readings(st["code"], step)
                is_defect = random.random() < 0.04  # ~4% defect rate for interesting traceability demo
                outcome = "defect" if is_defect else "ok"
                anomaly = 0.88 if is_defect else 0.02

                se_payload = {
                    "schema_version": "1.0",
                    "message_id": f"se-{uuid.uuid4().hex[:12]}",
                    "plant_id": plant_id,
                    "asset_id": st["code"],
                    "device_timestamp": now_iso,
                    "payload_type": "stage_event",
                    "payload": {
                        "unit_id": exiting_unit["unit_id"],
                        "machine_code": st["code"],
                        "area_code": st["area"],
                        "is_starved": False,
                        "entered_at": exiting_unit["entered_at"],
                        "exited_at": now_iso,
                        "outcome": outcome,
                        "anomaly_score": anomaly,
                        "sensor_snapshot": station_metrics,
                    },
                }
                client.publish(
                    f"plants/{plant_id}/modules/traceability/stage_event",
                    json.dumps(se_payload),
                    qos=1,
                )

                # End-of-line QC verdict
                qc_outcome = "defect" if is_defect else "pass"
                defect_type = "fill_level_low" if is_defect else None
                attr_stage = "filler_01" if is_defect else None
                qc_prob = 0.94 if is_defect else round(0.985 + random.uniform(0.001, 0.012), 3)

                qc_payload = {
                    "schema_version": "1.0",
                    "message_id": f"qc-{uuid.uuid4().hex[:12]}",
                    "plant_id": plant_id,
                    "asset_id": st["code"],
                    "device_timestamp": now_iso,
                    "payload_type": "qc_result",
                    "payload": {
                        "unit_id": exiting_unit["unit_id"],
                        "machine_code": st["code"],
                        "outcome": qc_outcome,
                        "probability": qc_prob,
                        "defect_type": defect_type,
                        "attributed_stage": attr_stage,
                    },
                }
                client.publish(
                    f"plants/{plant_id}/modules/quality/qc_result",
                    json.dumps(qc_payload),
                    qos=1,
                )

                if is_defect:
                    reject_counts[st["code"]] += 1
                    total_failed += 1
                else:
                    good_counts[st["code"]] += 1
                    total_passed += 1

                line_slots[4] = None

            # Advance units across earlier stations (capper -> inspector, filler -> capper, etc.)
            for idx in range(3, -1, -1):
                unit_at_idx = line_slots[idx]
                if unit_at_idx:
                    st = STATIONS[idx]
                    station_metrics = generate_readings(st["code"], step)
                    good_counts[st["code"]] += 1

                    # Publish stage event for leaving this station
                    se_payload = {
                        "schema_version": "1.0",
                        "message_id": f"se-{uuid.uuid4().hex[:12]}",
                        "plant_id": plant_id,
                        "asset_id": st["code"],
                        "device_timestamp": now_iso,
                        "payload_type": "stage_event",
                        "payload": {
                            "unit_id": unit_at_idx["unit_id"],
                            "machine_code": st["code"],
                            "area_code": st["area"],
                            "is_starved": False,
                            "entered_at": unit_at_idx["entered_at"],
                            "exited_at": now_iso,
                            "outcome": "ok",
                            "anomaly_score": round(random.uniform(0.01, 0.05), 3),
                            "sensor_snapshot": station_metrics,
                        },
                    }
                    client.publish(
                        f"plants/{plant_id}/modules/traceability/stage_event",
                        json.dumps(se_payload),
                        qos=1,
                    )

                    # Move to next station
                    line_slots[idx + 1] = {
                        "unit_id": unit_at_idx["unit_id"],
                        "entered_at": now_iso,
                        "entered_step": step,
                    }
                    line_slots[idx] = None

            # Introduce a new fresh bottle at station 0 (extractor_01)
            unit_counter += 1
            new_unit_id = f"BOTTLE-{date_prefix}-{unit_counter:04d}"
            line_slots[0] = {
                "unit_id": new_unit_id,
                "entered_at": now_iso,
                "entered_step": step,
            }

            # 2. Publish live telemetry for each station with current_unit_id and counters
            for idx, st in enumerate(STATIONS):
                current_unit = line_slots[idx]
                curr_unit_id = current_unit["unit_id"] if current_unit else None
                metrics = generate_readings(st["code"], step)

                telem_envelope = {
                    "schema_version": "1.0",
                    "plant_id": plant_id,
                    "asset_id": st["code"],
                    "device_timestamp": now_iso,
                    "message_id": f"msg-{st['code']}-{step}",
                    "payload": {
                        "status": "RUNNING",
                        "current_unit_id": curr_unit_id,
                        "good_count": good_counts[st["code"]],
                        "reject_count": reject_counts[st["code"]],
                        "metrics": metrics,
                    },
                }
                client.publish(
                    f"plants/{plant_id}/assets/{st['code']}/telemetry",
                    json.dumps(telem_envelope),
                    qos=0,
                )

            # 3. Publish inter-stage buffer queue depths
            queue_payload = {
                "schema_version": "1.0",
                "message_id": f"qd-{uuid.uuid4().hex[:12]}",
                "plant_id": plant_id,
                "device_timestamp": now_iso,
                "payload_type": "queue_depths",
                "payload": {
                    "extraction_pasteurization": 2 + (step % 2),
                    "bottling_capping": 3 + ((step + 1) % 3),
                    "inspection_packaging": 1 + (step % 2),
                },
            }
            client.publish(
                f"plants/{plant_id}/modules/traceability/queue_depths",
                json.dumps(queue_payload),
                qos=0,
            )

            active_in_flight = sum(1 for s in line_slots if s is not None)
            total_produced = total_passed + total_failed
            dur_str = f"{step}/{duration}" if duration > 0 else f"{step}"
            print(
                f"[{dur_str}] Line active | In-flight: {active_in_flight} bottles | "
                f"Completed: {total_produced} units (Pass: {total_passed}, Defect: {total_failed}) | "
                f"Lead unit: {new_unit_id}"
            )

            if duration > 0 and step >= duration:
                break

            time.sleep(cycle_delay)

    except KeyboardInterrupt:
        print("\nStopping simulation gracefully...")
    finally:
        client.loop_stop()
        client.disconnect()
        print(f"Simulation finished: Produced {total_passed + total_failed} units ({total_passed} passed, {total_failed} defect).")


if __name__ == "__main__":
    main()
