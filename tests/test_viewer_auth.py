import hashlib
import json
import logging
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
WATER_TOKEN = "district9_read_secret_token_889"


def find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


class LogCaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record):
        try:
            msg = self.format(record)
            self.records.append(msg)
        except Exception:  # noqa: BLE001, S110
            pass


@pytest.fixture(scope="module")
def auth_server():
    port = find_free_port()
    log_capture = LogCaptureHandler()
    log_capture.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    # Capture root, uvicorn, and app loggers
    for logger_name in (
        "",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "factory-backend",
    ):
        l = logging.getLogger(logger_name)
        l.addHandler(log_capture)
        l.setLevel(logging.DEBUG)

    config = uvicorn.Config(
        "main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
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
        pytest.fail("Auth server did not start in time")

    yield {
        "port": port,
        "base_url": base_url,
        "ws_url": f"ws://127.0.0.1:{port}",
        "server": srv,
        "log_capture": log_capture,
    }

    srv.should_exit = True
    thread.join(timeout=3.0)
    for logger_name in (
        "",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "factory-backend",
    ):
        logging.getLogger(logger_name).removeHandler(log_capture)


def test_token_plant_rest_without_token_returns_401(auth_server):
    """Every plant-scoped REST endpoint for a token plant requires Authorization: Bearer <token>. Missing returns 401."""
    base = auth_server["base_url"]

    # 1. Definition endpoint
    req = urllib.request.Request(f"{base}/api/plants/plant_water_district_9/definition")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 401
    body = json.loads(exc_info.value.read().decode())
    assert body.get("detail") == "Unauthorized"

    # 2. Latest machines endpoint
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/machines/latest"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 401

    # 3. WS ticket endpoint
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/ws-ticket",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 401


def test_token_plant_rest_with_wrong_token_returns_401(auth_server):
    """Wrong token returns 401 with generic detail, no hint about which part failed."""
    base = auth_server["base_url"]
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/definition",
        headers={"Authorization": "Bearer completely_bogus_token_xyz_999"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 401
    body = json.loads(exc_info.value.read().decode())
    assert body.get("detail") == "Unauthorized"


def test_token_plant_rest_with_valid_token_returns_200(auth_server):
    """Valid bearer token returns 200 OK and data."""
    base = auth_server["base_url"]
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/definition",
        headers={"Authorization": f"Bearer {WATER_TOKEN}"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert data["plant_id"] == "plant_water_district_9"

    # Machines latest
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/machines/latest",
        headers={"Authorization": f"Bearer {WATER_TOKEN}"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200


def test_demo_plant_stays_public(auth_server):
    """The demo plant (viewer_token null) stays public on REST and WebSocket without credentials."""
    base = auth_server["base_url"]
    ws_base = auth_server["ws_url"]

    # REST
    with urllib.request.urlopen(
        f"{base}/api/plants/plant_demo_membrane/definition"
    ) as resp:
        assert resp.status == 200

    with urllib.request.urlopen(
        f"{base}/api/plants/plant_demo_membrane/machines/latest"
    ) as resp:
        assert resp.status == 200

    # WebSocket without ticket
    async def connect_demo():
        uri = f"{ws_base}/ws/plant_demo_membrane/telemetry"
        async with websockets.connect(uri) as ws:
            assert ws.state.name in ("OPEN", "CONNECTING")

    import asyncio

    asyncio.run(connect_demo())


def test_get_plants_never_leaks_tokens_or_hashes(auth_server):
    """GET /api/plants stays public and never returns tokens or hashes; has_viewer_token is boolean."""
    base = auth_server["base_url"]
    with urllib.request.urlopen(f"{base}/api/plants") as resp:
        assert resp.status == 200
        plants = json.loads(resp.read().decode())

    by_id = {p["plant_id"]: p for p in plants}
    assert "plant_demo_membrane" in by_id
    assert "plant_water_district_9" in by_id

    water = by_id["plant_water_district_9"]
    assert water.get("has_viewer_token") is True
    assert "viewer_token" not in water
    assert "viewer_token_hash" not in water

    demo = by_id["plant_demo_membrane"]
    assert demo.get("has_viewer_token") is False
    assert "viewer_token" not in demo
    assert "viewer_token_hash" not in demo


def test_ws_ticket_single_use_and_plant_scoped(auth_server):
    """POST /api/plants/{plant_id}/ws-ticket issues ticket; WebSocket consumes on first use; reuse is 4401."""
    base = auth_server["base_url"]
    ws_base = auth_server["ws_url"]

    # Issue ticket
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/ws-ticket",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {WATER_TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode())
        ticket = body["ticket"]
        assert body["expires_in"] == 30

    import asyncio

    # 1. First use -> successful connect
    async def first_connect():
        uri = f"{ws_base}/ws/plant_water_district_9/telemetry?ticket={ticket}"
        async with websockets.connect(uri) as ws:
            assert ws.state.name in ("OPEN", "CONNECTING")
            await ws.close()

    asyncio.run(first_connect())

    # 2. Second use (reused ticket) -> refused with 4401
    async def reused_connect():
        uri = f"{ws_base}/ws/plant_water_district_9/telemetry?ticket={ticket}"
        with pytest.raises(websockets.exceptions.InvalidStatusCode) as exc:
            async with websockets.connect(uri):
                pass
        # or closed with code 4401
        assert exc.value.status_code == 4401 or "4401" in str(exc.value)

    async def reused_connect_close_code():
        uri = f"{ws_base}/ws/plant_water_district_9/telemetry?ticket={ticket}"
        try:
            async with websockets.connect(uri) as ws:
                await ws.recv()
        except websockets.exceptions.ConnectionClosed as cc:
            assert cc.code == 4401
        except websockets.exceptions.InvalidStatusCode as isc:
            assert isc.status_code == 4401

    asyncio.run(reused_connect_close_code())


def test_ws_ticket_wrong_plant_refused(auth_server):
    """Ticket issued for plant_water_district_9 cannot be used for plant_demo_membrane or other plant."""
    base = auth_server["base_url"]
    ws_base = auth_server["ws_url"]

    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/ws-ticket",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {WATER_TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        ticket = json.loads(resp.read().decode())["ticket"]

    import asyncio

    async def connect_wrong():
        # Attempt to use water plant ticket on another plant
        uri = f"{ws_base}/ws/other_plant/telemetry?ticket={ticket}"
        try:
            async with websockets.connect(uri) as ws:
                await ws.recv()
        except (
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.InvalidStatus,
            websockets.exceptions.InvalidStatusCode,
        ) as err:
            code = getattr(err, "code", None)
            if code is None and hasattr(err, "response"):
                code = getattr(err.response, "status_code", None)
            if code is None:
                code = getattr(err, "status_code", None)
            assert code in (4401, 404)

    asyncio.run(connect_wrong())


def test_ticket_store_purge_and_capacity_cap():
    """Unit test: TicketStore purges expired tickets on issue and caps at 1000 entries (raises 429)."""
    from main import TicketStore

    class FakeClock:
        def __init__(self, start=1000.0):
            self.now = start

        def __call__(self):
            return self.now

    clock = FakeClock()
    store = TicketStore(max_capacity=1000, ttl_seconds=30.0, clock=clock)

    # 1. Issue 5 tickets at t=1000
    t1 = store.issue("plant_1")
    assert store.validate_and_consume("plant_1", t1) is True
    assert store.validate_and_consume("plant_1", t1) is False  # single use

    # 2. Expiry check with fake clock
    t2 = store.issue("plant_1")
    clock.now += 31.0  # past 30s TTL
    assert store.validate_and_consume("plant_1", t2) is False  # expired

    # 3. Purging on issue
    store.issue("plant_1")
    # All expired tickets before clock.now should be purged
    assert len(store._tickets) == 1

    # 4. Capacity limit: 1000 entries
    clock.now = 2000.0
    store._tickets.clear()
    for i in range(1000):
        store.issue(f"plant_{i}")
    assert len(store._tickets) == 1000

    # Exceeding capacity raises exception that maps to 429
    with pytest.raises(Exception) as exc_info:
        store.issue("plant_overflow")
    assert "429" in str(exc_info.value) or "capacity" in str(exc_info.value).lower()


def test_cors_preflight_for_authorization_and_post(auth_server):
    """CORSMiddleware allows POST and OPTIONS preflight for Authorization header."""
    base = auth_server["base_url"]
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/ws-ticket",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
        method="OPTIONS",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        headers = dict(resp.headers)
        allow_methods = headers.get("access-control-allow-methods", "")
        allow_headers = headers.get("access-control-allow-headers", "")
        assert "POST" in allow_methods
        assert "authorization" in allow_headers.lower() or "*" in allow_headers


def test_sync_plant_definitions_stores_sha256_hash(tmp_path):
    """sync_plant_definitions stores SHA-256 hex digest in plants.viewer_token_hash (not plain text)."""
    from db import get_db_connection
    from ingest import sync_plant_definitions
    from main import init_platform_db
    from plant_definitions import load_plants

    test_db = tmp_path / "platform_test.db"
    init_platform_db(test_db)
    plants = load_plants(PLANTS_DIR)

    conn = get_db_connection(str(test_db))
    sync_plant_definitions(conn, plants)

    cur = conn.cursor()
    cur.execute(
        "SELECT viewer_token_hash FROM plants WHERE id = 'plant_water_district_9'"
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    stored_hash = row["viewer_token_hash"]
    expected_hash = hashlib.sha256(WATER_TOKEN.encode("utf-8")).hexdigest()
    assert stored_hash == expected_hash
    assert stored_hash != WATER_TOKEN


def test_log_hygiene_scans_all_logs_for_token_and_ticket(auth_server):
    """Full flow test captures logs and asserts that neither the token nor the ticket string is logged anywhere."""
    base = auth_server["base_url"]
    ws_base = auth_server["ws_url"]
    log_capture = auth_server["log_capture"]

    # 1. 401 without token
    req = urllib.request.Request(f"{base}/api/plants/plant_water_district_9/definition")
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(req)

    # 2. 401 with wrong token
    bogus_token = "secret_bogus_probe_12345"
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/definition",
        headers={"Authorization": f"Bearer {bogus_token}"},
    )
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(req)

    # 3. Issue ticket
    req = urllib.request.Request(
        f"{base}/api/plants/plant_water_district_9/ws-ticket",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {WATER_TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        ticket = json.loads(resp.read().decode())["ticket"]

    # 4. Connect WebSocket with ticket
    import asyncio

    async def ws_flow():
        uri = f"{ws_base}/ws/plant_water_district_9/telemetry?ticket={ticket}"
        async with websockets.connect(uri) as ws:
            await ws.close()

        # 5. Reused ticket refused
        try:
            async with websockets.connect(uri) as ws:
                await ws.recv()
        except (
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.InvalidStatusCode,
        ):
            pass

    asyncio.run(ws_flow())

    # Scan all captured logs
    all_logs = "\n".join(log_capture.records)
    assert WATER_TOKEN not in all_logs, f"Found raw token in logs! {all_logs}"
    assert bogus_token not in all_logs, f"Found bogus token in logs! {all_logs}"
    assert ticket not in all_logs, f"Found ticket in logs! {all_logs}"
