import asyncio
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

import pytest
import uvicorn
import websockets

from admin_auth import admin_rate_limiter
from database import get_db_connection
from ingest import IngestEngine
from main import (
    PLANTS_DIR,
    build_app,
    init_platform_db,
    seed_plants_if_empty,
)


def find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def run_test_server(app_instance):
    port = find_free_port()
    config = uvicorn.Config(
        app_instance,
        host="127.0.0.1",
        port=port,
        log_level="error",
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
            time.sleep(0.05)
    else:
        srv.should_exit = True
        thread.join(timeout=2.0)
        pytest.fail("Test server failed to start")

    return srv, thread, base_url, port


def api_request_with_raw(
    url: str,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
) -> tuple[int, dict[str, str], Any, str]:
    req_headers = {"User-Agent": "test-runner"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            raw = resp.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            return resp.status, resp_headers, parsed, raw
    except urllib.error.HTTPError as exc:
        resp_headers = {k.lower(): v for k, v in exc.headers.items()}
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = {"detail": raw}
        return exc.code, resp_headers, parsed, raw


@pytest.fixture
def admin_mutations_env(tmp_path, monkeypatch):
    db_file = tmp_path / "platform.db"
    monkeypatch.setenv("PLATFORM_DB_PATH", str(db_file))
    monkeypatch.setattr("main.PLATFORM_DB_PATH", str(db_file))
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "valid_test_admin_token_1234567890_32char")
    admin_rate_limiter.reset()

    init_platform_db(db_file)
    conn = get_db_connection(str(db_file))
    try:
        seed_plants_if_empty(conn, PLANTS_DIR)
    finally:
        conn.close()

    app = build_app()
    srv, thread, base_url, port = run_test_server(app)
    try:
        yield base_url, db_file, port
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)
        from main import viewer_tracker

        viewer_tracker._last_poll_at = None


def sample_plant_payload(plant_id: str = "plant_custom_01", token: str | None = None):
    return {
        "plant_id": plant_id,
        "name": f"Custom Plant {plant_id}",
        "timezone": "UTC",
        "viewer_token": token,
        "enabled_modules": ["core", "alarms"],
        "mqtt_credentials": [
            {
                "username": f"device_{plant_id}",
                "password": f"secret_pass_{plant_id}",
                "client_id": f"client_{plant_id}",
            }
        ],
        "areas": [
            {
                "area_code": "area_main",
                "name": "Main Production Area",
                "display_order": 1,
                "machines": [
                    {
                        "machine_code": "mach_01",
                        "name": "Machine 01",
                        "machine_type": "standard",
                        "display_order": 1,
                        "signals": [
                            {
                                "signal_code": "temperature",
                                "name": "Temperature",
                                "unit": "C",
                                "data_type": "float",
                                "display_order": 1,
                            },
                            {
                                "signal_code": "pressure",
                                "name": "Pressure",
                                "unit": "bar",
                                "data_type": "float",
                                "display_order": 2,
                            },
                        ],
                    },
                    {
                        "machine_code": "mach_02",
                        "name": "Machine 02",
                        "machine_type": "standard",
                        "display_order": 2,
                        "signals": [
                            {
                                "signal_code": "speed",
                                "name": "Speed",
                                "unit": "rpm",
                                "data_type": "float",
                                "display_order": 1,
                            }
                        ],
                    },
                ],
            }
        ],
    }


def test_admin_create_plant_201_valid_definition(admin_mutations_env):
    """POST /api/admin/plants creates a new plant definition with 201 Created."""
    base_url, db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    payload = sample_plant_payload("plant_created_test")

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201, f"Expected 201, got {status}: {body}"
    assert body.get("plant_id") == "plant_created_test"
    assert body.get("name") == "Custom Plant plant_created_test"

    # Verify in DB
    conn = get_db_connection(str(db_file))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM plants WHERE id = 'plant_created_test';")
        row = cur.fetchone()
        assert row is not None
        assert row["name"] == "Custom Plant plant_created_test"

        cur.execute(
            "SELECT username FROM plant_credentials WHERE plant_id = 'plant_created_test';"
        )
        creds = cur.fetchall()
        assert len(creds) == 1
        assert creds[0]["username"] == "device_plant_created_test"
    finally:
        conn.close()


def test_admin_create_plant_409_on_duplicate_id(admin_mutations_env):
    """POST /api/admin/plants returns 409 Conflict when plant_id already exists."""
    base_url, _db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    # Duplicate of seeded demo plant
    payload = sample_plant_payload("plant_demo_membrane")

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 409, f"Expected 409, got {status}: {body}"
    assert "already exists" in body.get("detail", "").lower()


def test_admin_create_plant_422_invalid_schema(admin_mutations_env):
    """POST /api/admin/plants returns 422 Unprocessable Entity when validation fails."""
    base_url, _db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    payload = sample_plant_payload("invalid_signal_plant")
    # Invalid signal code with spaces / uppercase
    payload["areas"][0]["machines"][0]["signals"][0]["signal_code"] = (
        "INVALID SIGNAL CODE!"
    )

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 422, f"Expected 422 on invalid schema, got {status}: {body}"


def test_admin_create_plant_response_never_contains_viewer_token_or_hash(
    admin_mutations_env,
):
    """POST /api/admin/plants response never leaks viewer token, hash, or password in keys or raw text."""
    base_url, _db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    canary_token = "canary_viewer_token_POST_SECRET_444"
    payload = sample_plant_payload("plant_redact_post", token=canary_token)

    status, _headers, body, raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201
    assert body.get("has_viewer_token") is True

    # Check raw text
    assert canary_token not in raw
    assert "secret_pass_plant_redact_post" not in raw
    assert '"viewer_token":' not in raw
    assert '"viewer_token_hash"' not in raw
    assert '"password":' not in raw
    assert '"password_hash"' not in raw


def test_admin_update_plant_put_does_not_touch_credentials(admin_mutations_env):
    """PUT /api/admin/plants/{id} updates plant metadata and areas without modifying plant_credentials."""
    base_url, db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    # First create custom plant
    create_payload = sample_plant_payload("plant_put_test")
    api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(create_payload).encode("utf-8"),
    )

    # In DB, verify original credential
    conn = get_db_connection(str(db_file))
    cur = conn.cursor()
    cur.execute(
        "SELECT password_hash FROM plant_credentials WHERE plant_id = 'plant_put_test';"
    )
    orig_cred = cur.fetchone()["password_hash"]
    conn.close()

    # Now PUT with modified credential in payload — PUT must ignore credential changes
    put_payload = dict(create_payload)
    put_payload["name"] = "Updated Plant Name PUT"
    put_payload["mqtt_credentials"] = [
        {
            "username": "device_plant_put_test",
            "password": "COMPLETELY_NEW_ATTEMPTED_PASSWORD",
            "client_id": "new_client",
        }
    ]

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_put_test",
        headers=auth_header,
        method="PUT",
        data=json.dumps(put_payload).encode("utf-8"),
    )
    assert status == 200, f"Expected 200, got {status}: {body}"
    assert body.get("name") == "Updated Plant Name PUT"

    # Verify credentials table was untouched!
    conn2 = get_db_connection(str(db_file))
    cur2 = conn2.cursor()
    cur2.execute(
        "SELECT password_hash FROM plant_credentials WHERE plant_id = 'plant_put_test';"
    )
    current_cred = cur2.fetchone()["password_hash"]
    conn2.close()
    assert current_cred == orig_cred, "PUT must not touch plant_credentials"


def test_admin_update_plant_put_without_viewer_token_preserves_existing_hash(
    admin_mutations_env,
):
    """PUT /api/admin/plants/{id} omitting viewer_token preserves existing viewer_token_hash."""
    base_url, db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    # Create plant with viewer_token configured
    create_payload = sample_plant_payload("plant_token_preserve_test")
    create_payload["viewer_token"] = "initial_secret_viewer_token_999"

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(create_payload).encode("utf-8"),
    )
    assert status == 201
    assert body.get("has_viewer_token") is True

    # Check hash in database
    conn = get_db_connection(str(db_file))
    cur = conn.cursor()
    cur.execute(
        "SELECT viewer_token_hash FROM plants WHERE id = 'plant_token_preserve_test';"
    )
    initial_hash = cur.fetchone()["viewer_token_hash"]
    conn.close()
    assert initial_hash is not None and len(initial_hash) == 64

    # Update plant metadata via PUT omitting viewer_token completely
    put_payload = sample_plant_payload("plant_token_preserve_test")
    put_payload["name"] = "Preserved Token Plant Name"
    # Ensure viewer_token is not present in put_payload
    put_payload.pop("viewer_token", None)

    status2, _headers2, body2, _raw2 = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_token_preserve_test",
        headers=auth_header,
        method="PUT",
        data=json.dumps(put_payload).encode("utf-8"),
    )
    assert status2 == 200
    assert body2.get("name") == "Preserved Token Plant Name"
    assert body2.get("has_viewer_token") is True

    # Verify database hash remains identical
    conn2 = get_db_connection(str(db_file))
    cur2 = conn2.cursor()
    cur2.execute(
        "SELECT viewer_token_hash FROM plants WHERE id = 'plant_token_preserve_test';"
    )
    post_put_hash = cur2.fetchone()["viewer_token_hash"]
    conn2.close()
    assert post_put_hash == initial_hash, "PUT without token field must keep existing hash"



def test_admin_update_plant_put_without_confirm_removals_returns_409(
    admin_mutations_env,
):
    """PUT /api/admin/plants/{id} removing machine returns 409 listing removals unless confirm_removals=true."""
    base_url, _db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    create_payload = sample_plant_payload("plant_removals_test")
    api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(create_payload).encode("utf-8"),
    )

    # Prepare update payload that removes mach_02
    put_payload = sample_plant_payload("plant_removals_test")
    # Remove machine 02
    put_payload["areas"][0]["machines"] = [put_payload["areas"][0]["machines"][0]]

    # Call PUT without ?confirm_removals=true -> must return 409
    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_removals_test",
        headers=auth_header,
        method="PUT",
        data=json.dumps(put_payload).encode("utf-8"),
    )
    assert status == 409, (
        f"Expected 409 when removing machine without confirmation, got {status}: {body}"
    )
    detail = body.get("detail", "")
    assert "confirm_removals" in str(detail).lower()


def test_admin_update_plant_put_with_confirm_removals_returns_200(admin_mutations_env):
    """PUT /api/admin/plants/{id}?confirm_removals=true purges removed machines/signals and returns 200."""
    base_url, db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    create_payload = sample_plant_payload("plant_confirm_test")
    api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(create_payload).encode("utf-8"),
    )

    # Insert some telemetry for mach_02 to verify it gets cleaned up
    conn = get_db_connection(str(db_file))
    conn.execute(
        """
        INSERT INTO telemetry_values (
            plant_id, machine_code, signal_code, device_timestamp,
            message_id, value_num
        ) VALUES ('plant_confirm_test', 'mach_02', 'speed', '2026-10-21T00:00:00Z', 'm1', 100.0);
        """
    )
    conn.commit()
    conn.close()

    # Prepare update payload that removes mach_02
    put_payload = sample_plant_payload("plant_confirm_test")
    put_payload["areas"][0]["machines"] = [put_payload["areas"][0]["machines"][0]]

    # Call PUT with ?confirm_removals=true
    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_confirm_test?confirm_removals=true",
        headers=auth_header,
        method="PUT",
        data=json.dumps(put_payload).encode("utf-8"),
    )
    assert status == 200, (
        f"Expected 200 with confirm_removals=true, got {status}: {body}"
    )

    # Verify in DB: mach_02 and its telemetry are gone
    conn2 = get_db_connection(str(db_file))
    cur = conn2.cursor()
    cur.execute(
        "SELECT machine_code FROM machines WHERE plant_id = 'plant_confirm_test';"
    )
    machs = [r["machine_code"] for r in cur.fetchall()]
    assert "mach_02" not in machs
    assert "mach_01" in machs

    cur.execute(
        "SELECT COUNT(*) FROM telemetry_values WHERE plant_id = 'plant_confirm_test' AND machine_code = 'mach_02';"
    )
    assert cur.fetchone()[0] == 0
    conn2.close()


def test_admin_delete_system_plant_returns_403(admin_mutations_env):
    """DELETE /api/admin/plants/plant_demo_membrane returns 403 Forbidden without deleting it."""
    base_url, db_file, _port = admin_mutations_env
    auth_header = {"Authorization": "Bearer valid_test_admin_token_1234567890_32char"}

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_demo_membrane",
        headers=auth_header,
        method="DELETE",
    )
    assert status == 403, (
        f"Expected 403 when deleting system plant, got {status}: {body}"
    )
    assert "system plant" in body.get("detail", "").lower()

    # Verify plant still in DB
    conn = get_db_connection(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT id FROM plants WHERE id = 'plant_demo_membrane';")
    assert cur.fetchone() is not None
    conn.close()


def test_admin_delete_custom_plant_200_and_purges_db_and_registry(admin_mutations_env):
    """DELETE /api/admin/plants/{id} purges plant from DB & registry in safe order; repeat returns 404."""
    base_url, db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    # Create plant
    create_payload = sample_plant_payload("plant_to_delete")
    api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(create_payload).encode("utf-8"),
    )

    # Delete plant
    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_to_delete",
        headers=auth_header,
        method="DELETE",
    )
    assert status == 200, f"Expected 200 on delete, got {status}: {body}"

    # Verify DB completely purged
    conn = get_db_connection(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM plants WHERE id = 'plant_to_delete';")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM machines WHERE plant_id = 'plant_to_delete';")
    assert cur.fetchone()[0] == 0
    conn.close()

    # Repeat delete returns 404 (safe to repeat after crash / idempotency)
    status2, _headers2, _body2, _raw2 = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_to_delete",
        headers=auth_header,
        method="DELETE",
    )
    assert status2 == 404


def test_admin_delete_plant_ticket_refused_and_queue_depths_404(admin_mutations_env):
    """After delete, ws-ticket is refused and queue-depths returns 404."""
    base_url, _db_file, _port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    create_payload = sample_plant_payload("plant_post_del_check")
    api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(create_payload).encode("utf-8"),
    )

    # Delete it
    del_status, _dh, _db, _dr = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_post_del_check",
        headers=auth_header,
        method="DELETE",
    )
    assert del_status == 200, f"Expected 200 on delete, got {del_status}"

    # 1. Ticket request refused
    t_status, _th, _t_body, _tr = api_request_with_raw(
        f"{base_url}/api/plants/plant_post_del_check/ws-ticket",
        method="POST",
    )
    assert t_status == 404

    # 2. Queue depths 404
    q_status, _qh, _q_body, _qr = api_request_with_raw(
        f"{base_url}/api/plants/plant_post_del_check/queue-depths",
        method="GET",
    )
    assert q_status == 404


@pytest.mark.anyio
async def test_admin_delete_plant_closes_websocket_with_code_4404(admin_mutations_env):
    """Active WebSocket viewer for a plant is disconnected with code 4404 when plant is deleted."""
    base_url, _db_file, port = admin_mutations_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    create_payload = sample_plant_payload("plant_ws_del_test")
    api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(create_payload).encode("utf-8"),
    )

    ws_url = f"ws://127.0.0.1:{port}/ws/plant_ws_del_test/telemetry"
    async with websockets.connect(ws_url) as ws:
        # Trigger delete in separate thread
        def do_delete():
            api_request_with_raw(
                f"{base_url}/api/admin/plants/plant_ws_del_test",
                headers=auth_header,
                method="DELETE",
            )

        t = threading.Thread(target=do_delete)
        t.start()
        t.join()

        # Wait for WS frame / close
        try:
            await asyncio.wait_for(ws.recv(), timeout=3.0)
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4404, f"Expected close code 4404, got {exc.code}"


@pytest.mark.anyio
async def test_admin_delete_concurrent_ingest_with_real_engine(tmp_path):
    """Real IngestEngine handles concurrent inserts for another plant while batched delete runs."""
    db_file = tmp_path / "concurrent_ingest.db"
    init_platform_db(db_file)

    conn = get_db_connection(str(db_file))
    seed_plants_if_empty(conn, PLANTS_DIR)

    # Insert plant_delete
    conn.execute(
        "INSERT INTO plants (id, name, timezone) VALUES ('plant_del_concurrent', 'Delete Me', 'UTC');"
    )
    conn.execute(
        "INSERT INTO areas (plant_id, area_code, name) VALUES ('plant_del_concurrent', 'a1', 'Area 1');"
    )
    conn.execute(
        "INSERT INTO machines (plant_id, machine_code, area_code, name) VALUES ('plant_del_concurrent', 'm1', 'a1', 'M1');"
    )
    conn.execute(
        "INSERT INTO signals (plant_id, machine_code, signal_code, name) VALUES ('plant_del_concurrent', 'm1', 's1', 'S1');"
    )

    # Insert 10,000 rows for plant_del_concurrent
    rows = [
        (
            "plant_del_concurrent",
            "m1",
            "s1",
            f"2026-10-21T00:00:{i % 60:02d}Z",
            f"2026-10-21T00:00:{i % 60:02d}Z",
            f"msg_{i}",
            float(i),
            None,
        )
        for i in range(10000)
    ]
    conn.executemany(
        """
        INSERT INTO telemetry_values (plant_id, machine_code, signal_code, device_timestamp, received_at, message_id, value_num, value_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    conn.commit()
    conn.close()

    from main import plants_registry

    engine = IngestEngine(db_path=db_file, plants=plants_registry)
    await engine.start()

    stop_event = asyncio.Event()
    ingest_count = 0

    async def ingest_task():
        nonlocal ingest_count
        i = 0
        while not stop_event.is_set():
            payload = {
                "schema_version": "1.0",
                "plant_id": "plant_demo_membrane",
                "asset_id": "hm_01",
                "device_timestamp": datetime.now(UTC).isoformat(),
                "message_id": f"conc_msg_{i}",
                "payload": {"metrics": {"mold_temperature_actual": 65.0 + (i % 5)}},
            }
            res = await engine.handle_telemetry(payload, "plant_demo_membrane", "hm_01")
            if res:
                ingest_count += 1
            i += 1
            await asyncio.sleep(0.005)

    worker = asyncio.create_task(ingest_task())

    # Perform batched delete
    del_conn = get_db_connection(str(db_file))
    from main import _batched_delete_telemetry

    await asyncio.to_thread(
        _batched_delete_telemetry, del_conn, "plant_del_concurrent", batch_size=2000
    )
    del_conn.execute("DELETE FROM plants WHERE id = 'plant_del_concurrent';")
    del_conn.commit()
    del_conn.close()

    stop_event.set()
    await worker
    await engine.flush()
    await engine.stop()

    assert engine.dropped_total == 0

    check_conn = get_db_connection(str(db_file))
    cur = check_conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM telemetry_values WHERE plant_id = 'plant_del_concurrent';"
    )
    assert cur.fetchone()[0] == 0

    cur.execute(
        "SELECT COUNT(*) FROM telemetry_values WHERE plant_id = 'plant_demo_membrane';"
    )
    membrane_count = cur.fetchone()[0]
    assert membrane_count > 0, (
        "Telemetry for plant_demo_membrane must survive without errors"
    )
    check_conn.close()


@pytest.mark.anyio
async def test_ingest_flush_race_skips_deleted_plant_without_breaking_batch(tmp_path):
    """IngestEngine handles flush race condition when a plant is deleted right during flush."""
    db_file = tmp_path / "flush_race.db"
    init_platform_db(db_file)
    conn = get_db_connection(str(db_file))
    seed_plants_if_empty(conn, PLANTS_DIR)

    # Add temporary plant
    conn.execute(
        "INSERT INTO plants (id, name, timezone) VALUES ('plant_race_test', 'Race', 'UTC');"
    )
    conn.execute(
        "INSERT INTO areas (plant_id, area_code, name) VALUES ('plant_race_test', 'a1', 'A1');"
    )
    conn.execute(
        "INSERT INTO machines (plant_id, machine_code, area_code, name) VALUES ('plant_race_test', 'm1', 'a1', 'M1');"
    )
    conn.execute(
        "INSERT INTO signals (plant_id, machine_code, signal_code, name) VALUES ('plant_race_test', 'm1', 's1', 'S1');"
    )
    conn.commit()
    conn.close()

    from main import plants_registry

    engine = IngestEngine(db_path=db_file, plants=plants_registry)

    # Enqueue valid message for membrane
    await engine.handle_telemetry(
        {
            "schema_version": "1.0",
            "plant_id": "plant_demo_membrane",
            "asset_id": "hm_01",
            "device_timestamp": datetime.now(UTC).isoformat(),
            "message_id": "valid_msg_survives",
            "payload": {"metrics": {"mold_temperature_actual": 66.5}},
        },
        "plant_demo_membrane",
        "hm_01",
    )

    # Directly inject an unvalidated row for plant_race_test into engine's queue to simulate
    # enqueue passing right before delete occurs
    race_row = (
        "plant_race_test",
        "m1",
        "s1",
        datetime.now(UTC).isoformat(),
        datetime.now(UTC).isoformat(),
        "race_msg_1",
        42.0,
        None,
    )
    engine._queue.put_nowait(([race_row], None))

    # Now delete plant_race_test from DB before flush runs
    del_conn = get_db_connection(str(db_file))
    del_conn.execute("DELETE FROM plants WHERE id = 'plant_race_test';")
    del_conn.commit()
    del_conn.close()

    # Flush the batch! The batch contains both valid membrane row and the race_row for deleted plant
    await engine.flush()
    await engine.stop()

    # Check DB: membrane row must be present in telemetry_values!
    check_conn = get_db_connection(str(db_file))
    cur = check_conn.cursor()
    cur.execute(
        "SELECT message_id FROM telemetry_values WHERE plant_id = 'plant_demo_membrane' AND message_id = 'valid_msg_survives';"
    )
    assert cur.fetchone() is not None, (
        "Valid row in the same batch must survive and commit successfully"
    )
    check_conn.close()
