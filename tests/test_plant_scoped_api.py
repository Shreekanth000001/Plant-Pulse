import asyncio
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

import pytest
import uvicorn
import websockets

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"


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

    yield {
        "port": port,
        "base_url": base_url,
        "ws_url": f"ws://127.0.0.1:{port}",
        "server": srv,
    }

    srv.should_exit = True
    thread.join(timeout=3.0)


def http_get(url: str) -> tuple[int, dict | list]:
    req = urllib.request.Request(url, headers={"User-Agent": "test-runner"})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            parsed = {"error": body}
        return exc.code, parsed


def test_criterion_1_lifespan_syncs_plant_definitions_and_starts_ingest(server):
    """Criterion 1: App lifespan loads plants, syncs definitions to platform.db, and starts IngestEngine."""
    import main

    assert hasattr(main, "ingest_engine") and main.ingest_engine is not None
    assert main.ingest_engine._running is True
    assert hasattr(main, "plants_registry")
    assert len(main.plants_registry) >= 2
    assert "plant_demo_membrane" in main.plants_registry
    assert "plant_water_district_9" in main.plants_registry


def test_criterion_2_get_plants_list(server):
    """Criterion 2: GET /api/plants returns list of registered plants with metadata."""
    status, data = http_get(f"{server['base_url']}/api/plants")
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert isinstance(data, list)
    plant_ids = {p["plant_id"] for p in data}
    assert "plant_demo_membrane" in plant_ids
    assert "plant_water_district_9" in plant_ids

    # Verify metadata fields and no secrets leaked
    for p in data:
        assert "plant_id" in p
        assert "name" in p
        assert "timezone" in p
        assert "enabled_modules" in p
        assert "viewer_token" not in p
        assert "mqtt_credentials" not in p


def test_criterion_3_get_plant_definition(server):
    """Criterion 3: GET /api/plants/{plant_id}/definition returns definition or 404."""
    # 1. Valid plant returns definition
    status, data = http_get(
        f"{server['base_url']}/api/plants/plant_demo_membrane/definition"
    )
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert data["plant_id"] == "plant_demo_membrane"
    assert "areas" in data
    assert len(data["areas"]) > 0

    # 2. Unknown plant returns 404
    status, data = http_get(
        f"{server['base_url']}/api/plants/unknown_plant_xyz/definition"
    )
    assert status == 404, f"Expected 404 for unknown plant, got {status}: {data}"


def test_criterion_4_get_plant_machines_latest(server):
    """Criterion 4: GET /api/plants/{plant_id}/machines/latest returns latest machine telemetry or 404."""
    # 1. Valid plant returns machines
    status, data = http_get(
        f"{server['base_url']}/api/plants/plant_demo_membrane/machines/latest"
    )
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert isinstance(data, list)
    assert len(data) == 11, (
        f"Expected 11 machines for demo membrane plant, got {len(data)}"
    )
    first_machine = data[0]
    assert "machine_code" in first_machine
    assert "area_code" in first_machine
    assert "name" in first_machine
    assert "state" in first_machine
    assert "signals" in first_machine

    # 2. Unknown plant returns 404
    status, data = http_get(
        f"{server['base_url']}/api/plants/unknown_plant_xyz/machines/latest"
    )
    assert status == 404, f"Expected 404 for unknown plant, got {status}: {data}"


@pytest.mark.anyio
async def test_criterion_5_and_6_and_7_websocket_connection_rules(server):
    """Criteria 5, 6, 7:
    - Demo plant (viewer_token is null) accepts viewers.
    - Operator plant (viewer_token is not null) refuses with close code 4401.
    - Unknown plant returns 404.
    """
    ws_base = server["ws_url"]

    # Criterion 5: Demo plant accepts viewer
    async with websockets.connect(f"{ws_base}/ws/plant_demo_membrane/telemetry") as ws:
        assert ws.state.name == "OPEN"

    # Criterion 6: Operator plant with viewer_token is refused with 4401
    with pytest.raises(websockets.exceptions.ConnectionClosed) as excinfo:
        async with websockets.connect(
            f"{ws_base}/ws/plant_water_district_9/telemetry"
        ) as ws:
            await ws.recv()
    assert excinfo.value.rcvd is not None
    assert excinfo.value.rcvd.code == 4401, (
        f"Expected close code 4401, got {excinfo.value.rcvd.code}"
    )

    # Criterion 7: Unknown plant returns 404
    with pytest.raises(websockets.exceptions.InvalidStatus) as excinfo:
        async with websockets.connect(
            f"{ws_base}/ws/unknown_plant_xyz/telemetry"
        ) as ws:
            await ws.recv()
    assert excinfo.value.response.status_code == 404


@pytest.mark.anyio
async def test_criterion_8_websocket_cross_plant_isolation(server):
    """Criterion 8: Plant A viewer receives ZERO frames published for Plant B."""
    import main

    ws_base = server["ws_url"]

    # Connect viewer to Plant A (plant_demo_membrane)
    async with websockets.connect(
        f"{ws_base}/ws/plant_demo_membrane/telemetry"
    ) as ws_a:
        # Dispatch message for Plant B (plant_water_district_9)
        plant_b_payload = {
            "schema_version": "1.0",
            "message_id": "test-b-001",
            "plant_id": "plant_water_district_9",
            "asset_id": "pump_01",
            "device_timestamp": "2026-10-18T12:00:00Z",
            "payload_type": "telemetry",
            "payload": {
                "status": "RUNNING",
                "metrics": {"discharge_pressure": 62.5},
            },
        }

        # Dispatch through topic_router or broadcast
        await main.topic_router.dispatch(
            "plants/plant_water_district_9/assets/pump_01/telemetry",
            plant_b_payload,
        )

        # Plant A viewer should receive NOTHING within 0.5s
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(ws_a.recv(), timeout=0.5)

        # Now dispatch message for Plant A
        plant_a_payload = {
            "schema_version": "1.0",
            "message_id": "test-a-001",
            "plant_id": "plant_demo_membrane",
            "asset_id": "hm_01",
            "device_timestamp": "2026-10-18T12:00:00Z",
            "payload_type": "telemetry",
            "payload": {
                "status": "RUNNING",
                "metrics": {"mold_temperature_actual": 65.2},
            },
        }
        await main.topic_router.dispatch(
            "plants/plant_demo_membrane/assets/hm_01/telemetry",
            plant_a_payload,
        )

        # Plant A viewer receives the frame
        msg_raw = await asyncio.wait_for(ws_a.recv(), timeout=2.0)
        frame = json.loads(msg_raw)
        assert frame["topic"] == "plants/plant_demo_membrane/assets/hm_01/telemetry"
        assert frame["payload"]["message_id"] == "test-a-001"


def test_criterion_9_legacy_endpoints_preserved(server):
    """Criterion 9: Legacy endpoints remain functional without modification."""
    status, data = http_get(f"{server['base_url']}/api/machines/latest")
    assert status == 200, f"Legacy /api/machines/latest returned {status}: {data}"
    assert isinstance(data, list)

    status, data = http_get(f"{server['base_url']}/api/queue-depths")
    assert status == 200, f"Legacy /api/queue-depths returned {status}: {data}"

    status, data = http_get(f"{server['base_url']}/api/units")
    assert status == 200, f"Legacy /api/units returned {status}: {data}"
