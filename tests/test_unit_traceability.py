import asyncio
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime

import pytest
import uvicorn

import main


def find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = find_free_port()
    config = uvicorn.Config(
        "main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=0.2) as resp:
                if resp.status == 200:
                    break
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    else:
        pytest.fail("Server did not start in time")

    yield {"base_url": base_url, "port": port}


def http_get(url: str) -> tuple[int, dict | list]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read().decode("utf-8"))
        return exc.code, data


def test_unit_traceability_lifecycle_from_canonical_topics(server):
    unit_id = f"unit_test_trace_{int(time.time())}"

    # 1. Unknown unit returns 404
    status, body = http_get(f"{server['base_url']}/api/units/{unit_id}")
    assert status == 404, f"Expected 404 for unknown unit, got {status}: {body}"

    # 2. Dispatch stage_event for Stage 1 (Housing)
    stage1_payload = {
        "schema_version": "1.0",
        "message_id": f"msg_stage_1_{unit_id}",
        "plant_id": "plant_demo_membrane",
        "asset_id": "hm_01",
        "device_timestamp": datetime.now(UTC).isoformat(),
        "payload_type": "stage_event",
        "payload": {
            "unit_id": unit_id,
            "machine_code": "hm_01",
            "area_code": "housing",
            "is_starved": False,
            "entered_at": datetime.now(UTC).isoformat(),
            "exited_at": datetime.now(UTC).isoformat(),
            "outcome": "ok",
            "anomaly_score": 0.05,
            "sensor_snapshot": {
                "mold_temperature_actual": 65.2,
                "vibration_mms": 2.1,
            },
        },
    }

    asyncio.run(
        main.topic_router.dispatch(
            "plants/plant_demo_membrane/modules/traceability/stage_event",
            stage1_payload,
        )
    )

    # 3. Unit should now exist with status in_progress and 1 stage
    status, unit_data = http_get(f"{server['base_url']}/api/units/{unit_id}")
    assert status == 200, f"Expected 200 for created unit, got {status}: {unit_data}"
    assert unit_data["unit_id"] == unit_id
    assert unit_data["status"] == "in_progress"
    assert len(unit_data["stages"]) == 1
    assert unit_data["stages"][0]["machine_id"] == "hm_01"
    assert unit_data["stages"][0]["sub_facility"] == "housing"
    assert unit_data["stages"][0]["outcome"] == "ok"
    assert unit_data["qc_result"] is None

    # 4. Dispatch stage_event for Stage 2 (Casting)
    stage2_payload = {
        "schema_version": "1.0",
        "message_id": f"msg_stage_2_{unit_id}",
        "plant_id": "plant_demo_membrane",
        "asset_id": "cs_01",
        "device_timestamp": datetime.now(UTC).isoformat(),
        "payload_type": "stage_event",
        "payload": {
            "unit_id": unit_id,
            "machine_code": "cs_01",
            "area_code": "casting",
            "is_starved": False,
            "entered_at": datetime.now(UTC).isoformat(),
            "exited_at": datetime.now(UTC).isoformat(),
            "outcome": "ok",
            "anomaly_score": 0.08,
            "sensor_snapshot": {
                "extrusion_temp_actual": 64.8,
                "viscosity_actual": 34.1,
            },
        },
    }

    asyncio.run(
        main.topic_router.dispatch(
            "plants/plant_demo_membrane/modules/traceability/stage_event",
            stage2_payload,
        )
    )

    # 5. Unit should now have 2 stages
    status, unit_data = http_get(f"{server['base_url']}/api/units/{unit_id}")
    assert status == 200
    assert len(unit_data["stages"]) == 2
    assert unit_data["stages"][1]["machine_id"] == "cs_01"
    assert unit_data["stages"][1]["sub_facility"] == "casting"

    # 6. Dispatch qc_result
    qc_payload = {
        "schema_version": "1.0",
        "message_id": f"msg_qc_1_{unit_id}",
        "plant_id": "plant_demo_membrane",
        "asset_id": "qc_01",
        "device_timestamp": datetime.now(UTC).isoformat(),
        "payload_type": "qc_result",
        "payload": {
            "unit_id": unit_id,
            "machine_code": "qc_01",
            "outcome": "pass",
            "probability": 0.985,
            "defect_type": None,
            "attributed_stage": None,
        },
    }

    asyncio.run(
        main.topic_router.dispatch(
            "plants/plant_demo_membrane/modules/quality/qc_result",
            qc_payload,
        )
    )

    # 7. Unit status updated to passed, qc_result populated
    status, unit_data = http_get(f"{server['base_url']}/api/units/{unit_id}")
    assert status == 200
    assert unit_data["status"] == "passed"
    assert unit_data["qc_result"] is not None
    assert unit_data["qc_result"]["outcome"] == "pass"
    assert unit_data["qc_result"]["probability"] == 0.985

    # 8. Check recent units list
    status, recent = http_get(f"{server['base_url']}/api/units?limit=50")
    assert status == 200
    assert isinstance(recent, list)
    matching = [u for u in recent if u["unit_id"] == unit_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "passed"


def test_active_unit_in_progress_from_telemetry(server):
    """When a unit is born at Housing Molder, telemetry reports current_unit_id
    while the machine is running. GET /api/units/{unit_id} must return 200 with
    status 'in_progress' and not 404, even before the first stage_event completes."""
    unit_id = f"unit_live_housing_{int(time.time())}"

    # 1. Unknown before telemetry
    status, _body = http_get(f"{server['base_url']}/api/units/{unit_id}")
    assert status == 404

    # 2. Dispatch telemetry with current_unit_id from hm_01
    telemetry_payload = {
        "schema_version": "1.0",
        "message_id": f"msg_telemetry_{unit_id}",
        "plant_id": "plant_demo_membrane",
        "asset_id": "hm_01",
        "device_timestamp": datetime.now(UTC).isoformat(),
        "payload_type": "telemetry",
        "payload": {
            "status": "RUNNING",
            "sub_status": "MOLDING",
            "current_unit_id": unit_id,
            "starved": False,
            "good_count": 5,
            "reject_count": 0,
            "metrics": {
                "mold_temperature_actual": 65.0,
                "vibration_mms": 1.2,
            },
        },
    }

    asyncio.run(
        main.topic_router.dispatch(
            "plants/plant_demo_membrane/assets/hm_01/telemetry",
            telemetry_payload,
        )
    )

    # 3. GET /api/units/{unit_id} must return 200 OK with in_progress status
    status, unit_data = http_get(f"{server['base_url']}/api/units/{unit_id}")
    assert status == 200, f"Expected 200, got {status}: {unit_data}"
    assert unit_data["unit_id"] == unit_id
    assert unit_data["status"] == "in_progress"
    assert unit_data["stages"] == []
    assert unit_data["qc_result"] is None

    # 4. Check that recent units endpoint lists this unit
    status, recent = http_get(f"{server['base_url']}/api/units?limit=50")
    assert status == 200
    matching = [u for u in recent if u["unit_id"] == unit_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "in_progress"
