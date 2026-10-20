import asyncio
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
import uvicorn

WATER_TOKEN = "district9_read_secret_token_889"


def find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def history_server():
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
        pytest.fail("History server did not start in time")

    yield {
        "port": port,
        "base_url": base_url,
        "server": srv,
    }

    srv.should_exit = True
    thread.join(timeout=3.0)


def api_get(url: str, token: str | None = None) -> tuple[int, dict]:
    headers = {"User-Agent": "test-runner"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return exc.code, {"detail": body}


def test_history_water_plant_without_token_returns_401(history_server):
    """Water plant requires bearer token; request without Authorization header returns 401."""
    url = f"{history_server['base_url']}/api/plants/plant_water_district_9/machines/pump_01/signals/discharge_pressure_bar/history"
    status, data = api_get(url, token=None)
    assert status == 401, f"Expected 401 but got {status}: {data}"
    assert data.get("detail") == "Unauthorized"


def test_history_water_plant_with_valid_bearer_returns_200(history_server):
    """Water plant with valid Bearer token returns 200 OK."""
    url = f"{history_server['base_url']}/api/plants/plant_water_district_9/machines/pump_01/signals/discharge_pressure_bar/history"
    status, data = api_get(url, token=WATER_TOKEN)
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert data["plant_id"] == "plant_water_district_9"
    assert data["machine_code"] == "pump_01"
    assert data["signal_code"] == "discharge_pressure_bar"
    assert "data" in data
    assert data["total_points"] == len(data["data"])


def test_history_demo_plant_returns_200_without_token(history_server):
    """Public demo plant returns 200 OK without any bearer token."""
    url = f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/signals/mold_temperature_actual/history"
    status, data = api_get(url, token=None)
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert data["plant_id"] == "plant_demo_membrane"
    assert data["machine_code"] == "hm_01"
    assert data["signal_code"] == "mold_temperature_actual"
    assert "data" in data
    assert data["total_points"] == len(data["data"])


def test_history_exact_500_unaligned_never_exceeds_500(history_server):
    """With points=500 and worst-case unaligned start, bucket count strictly does not exceed 500."""
    import main

    assert main.ingest_engine is not None

    now = datetime.now(UTC)
    now_epoch = int(now.timestamp())
    target_start = now_epoch - 18000
    start_epoch = target_start - (target_start % 36) + 10
    span_sec = 18000
    end_epoch = start_epoch + span_sec

    start_dt = datetime.fromtimestamp(start_epoch, tz=UTC)
    end_dt = datetime.fromtimestamp(end_epoch, tz=UTC)

    k_start = start_epoch // 36
    k_end = end_epoch // 36

    async def seed():
        for k in range(k_start, k_end + 1):
            if k == k_start:
                ep = start_epoch
            elif k == k_end:
                ep = end_epoch
            else:
                ep = k * 36 + 1
            dt = datetime.fromtimestamp(ep, tz=UTC)
            payload = {
                "schema_version": "1.0",
                "plant_id": "plant_demo_membrane",
                "asset_id": "hm_02",
                "device_timestamp": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "message_id": f"unaligned-500-{k}-{uuid.uuid4()}",
                "payload": {"metrics": {"mold_temperature_actual": 42.0}},
            }
            ok = await main.ingest_engine.handle_telemetry(
                payload, "plant_demo_membrane", "hm_02"
            )
            assert ok, "IngestEngine returned False for telemetry ingestion"
        await main.ingest_engine.flush()

    asyncio.run(seed())

    start_ts = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_ts = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_02/"
        f"signals/mold_temperature_actual/history?start={start_ts}&end={end_ts}&points=500"
    )
    status, data = api_get(url)
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert len(data["data"]) <= 500, f"Bucket count {len(data['data'])} exceeded 500!"
    assert data["total_points"] == len(data["data"])


def test_history_timestamp_formats_land_in_correct_bucket(history_server):
    """Real IngestEngine seeds timestamps with Z, +05:30, and microsecond 0 into the exact UTC bucket."""
    import main

    assert main.ingest_engine is not None

    base_dt = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=2
    )
    # Three test inputs representing the same logical minute but different string formats
    ts_z = base_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Same minute expressed in +05:30 timezone (+5h 30m offset)
    ts_offset = (base_dt + timedelta(hours=5, minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%S+05:30"
    )
    # Microsecond 0 with +00:00
    ts_zero_us = base_dt.strftime("%Y-%m-%dT%H:%M:%S.000000+00:00")

    async def seed():
        for i, ts in enumerate([ts_z, ts_offset, ts_zero_us]):
            payload = {
                "schema_version": "1.0",
                "plant_id": "plant_demo_membrane",
                "asset_id": "hm_01",
                "device_timestamp": ts,
                "message_id": f"test-seed-msg-{uuid.uuid4()}",
                "payload": {"metrics": {"mold_temperature_actual": 60.0 + i * 5.0}},
            }
            await main.ingest_engine.handle_telemetry(
                payload, "plant_demo_membrane", "hm_01"
            )
        await main.ingest_engine.flush()

    asyncio.run(seed())

    # Query range encompassing this hour
    start = (base_dt - timedelta(minutes=5)).isoformat()
    end = (base_dt + timedelta(minutes=5)).isoformat()
    url = (
        f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/"
        f"signals/mold_temperature_actual/history?start={start}&end={end}&points=100"
    )
    status, data = api_get(url)
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert len(data["data"]) >= 1
    # Check that all 3 samples were aggregated together in the same UTC bucket
    bucket_sec = data["bucket_seconds"]
    expected_bucket_epoch = (int(base_dt.timestamp()) // bucket_sec) * bucket_sec
    expected_iso_z = datetime.fromtimestamp(expected_bucket_epoch, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    matching_bucket = None
    for b in data["data"]:
        if b["timestamp"] == expected_iso_z:
            matching_bucket = b
            break

    assert matching_bucket is not None, (
        f"Expected bucket {expected_iso_z} not found in {data['data']}"
    )
    assert matching_bucket["count"] >= 3
    assert matching_bucket["min"] == 60.0
    assert matching_bucket["max"] == 70.0


def test_history_ignores_null_value_num(history_server):
    """Rows with NULL value_num (non-numeric text values) are excluded from numeric aggregations."""
    import sqlite3

    import main

    now = datetime.now(UTC)
    ts = (now - timedelta(minutes=10)).isoformat()

    conn = sqlite3.connect(main.PLATFORM_DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO telemetry_values (
                plant_id, machine_code, signal_code, device_timestamp,
                received_at, message_id, value_num, value_text
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                "plant_demo_membrane",
                "hm_01",
                "mold_temperature_actual",
                ts,
                ts,
                f"null-test-{uuid.uuid4()}",
                "error_state_text",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Query range including ts
    start = (now - timedelta(minutes=15)).isoformat()
    end = (now - timedelta(minutes=5)).isoformat()
    url = (
        f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/"
        f"signals/mold_temperature_actual/history?start={start}&end={end}"
    )
    status, data = api_get(url)
    assert status == 200
    for b in data["data"]:
        assert b["avg"] is not None
        assert b["min"] is not None
        assert b["max"] is not None


def test_history_empty_range_returns_empty_list(history_server):
    """Querying a time window far in the past returns 200 OK with data: []."""
    start = "2020-01-01T00:00:00Z"
    end = "2020-01-01T01:00:00Z"
    url = (
        f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/"
        f"signals/mold_temperature_actual/history?start={start}&end={end}"
    )
    status, data = api_get(url)
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert data["data"] == []
    assert data["total_points"] == 0


def test_history_unknown_machine_or_signal_returns_404(history_server):
    """Unknown machine or unknown signal returns 404 Not Found."""
    # Unknown machine
    url1 = f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/nonexistent_m/signals/mold_temperature_actual/history"
    status1, data1 = api_get(url1)
    assert status1 == 404, f"Expected 404 but got {status1}: {data1}"

    # Unknown signal
    url2 = f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/signals/nonexistent_sig/history"
    status2, data2 = api_get(url2)
    assert status2 == 404, f"Expected 404 but got {status2}: {data2}"


def test_history_non_numeric_signal_returns_400(history_server):
    """Signal with non-numeric data_type (bool or string) returns 400 Bad Request."""
    import main

    plant = main.plants_registry["plant_demo_membrane"]
    # Temporarily register a test boolean signal on hm_01
    from plant_definitions import SignalDefinition

    bool_sig = SignalDefinition(
        signal_code="test_bool_sig",
        name="Test Bool Signal",
        data_type="bool",
    )
    m = next(m for a in plant.areas for m in a.machines if m.machine_code == "hm_01")
    m.signals.append(bool_sig)

    try:
        url = f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/signals/test_bool_sig/history"
        status, data = api_get(url)
        assert status == 400, f"Expected 400 but got {status}: {data}"
        assert "non-numeric" in data.get("detail", "").lower()
    finally:
        m.signals.remove(bool_sig)


def test_history_range_exceeding_24h_rejected_400(history_server):
    """Time range exceeding 24 hours returns 400 Bad Request."""
    now = datetime.now(UTC)
    start = (now - timedelta(hours=24, seconds=5)).isoformat()
    end = now.isoformat()
    url = (
        f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/"
        f"signals/mold_temperature_actual/history?start={start}&end={end}"
    )
    status, data = api_get(url)
    assert status == 400, f"Expected 400 but got {status}: {data}"
    assert "24 hours" in data.get("detail", "").lower()


def test_history_start_greater_than_end_returns_400(history_server):
    """start > end returns 400 Bad Request."""
    start = "2026-10-20T20:00:00Z"
    end = "2026-10-20T19:00:00Z"
    url = (
        f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/"
        f"signals/mold_temperature_actual/history?start={start}&end={end}"
    )
    status, data = api_get(url)
    assert status == 400, f"Expected 400 but got {status}: {data}"


def test_history_range_less_than_10s_returns_400(history_server):
    """Range less than 10 seconds returns 400 Bad Request."""
    start = "2026-10-20T19:00:00Z"
    end = "2026-10-20T19:00:05Z"
    url = (
        f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/"
        f"signals/mold_temperature_actual/history?start={start}&end={end}"
    )
    status, data = api_get(url)
    assert status == 400, f"Expected 400 but got {status}: {data}"


def test_history_unparseable_timestamp_returns_400(history_server):
    """Unparsable timestamp string returns 400 Bad Request."""
    start = "invalid-date-not-iso"
    end = "2026-10-20T19:00:00Z"
    url = (
        f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/"
        f"signals/mold_temperature_actual/history?start={start}&end={end}"
    )
    status, data = api_get(url)
    assert status == 400, f"Expected 400 but got {status}: {data}"


def test_history_bucket_timestamps_end_with_z(history_server):
    """Returned bucket timestamps end with Z and match ISO UTC format."""
    url = f"{history_server['base_url']}/api/plants/plant_demo_membrane/machines/hm_01/signals/mold_temperature_actual/history"
    status, data = api_get(url)
    assert status == 200, f"Expected 200 but got {status}: {data}"
    assert "start" in data and data["start"].endswith("Z")
    assert "end" in data and data["end"].endswith("Z")
    for point in data["data"]:
        assert point["timestamp"].endswith("Z"), (
            f"Timestamp {point['timestamp']} does not end with Z"
        )
