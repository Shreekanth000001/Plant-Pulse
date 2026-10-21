import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from typing import Any

import pytest
import uvicorn

from admin_auth import admin_rate_limiter
from db import get_db_connection
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

    return srv, thread, base_url


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


def assert_no_sensitive_keys(
    data: Any,
    sensitive_keys=("viewer_token", "viewer_token_hash", "password", "password_hash"),
):
    if isinstance(data, dict):
        for k, v in data.items():
            assert k not in sensitive_keys, (
                f"Found sensitive key '{k}' in response body: {data}"
            )
            assert_no_sensitive_keys(v, sensitive_keys)
    elif isinstance(data, list):
        for item in data:
            assert_no_sensitive_keys(item, sensitive_keys)


@pytest.fixture
def admin_test_env(tmp_path, monkeypatch):
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
    srv, thread, base_url = run_test_server(app)
    try:
        yield base_url, db_file
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_admin_plants_401_without_token(admin_test_env):
    """Admin read routes return 401 Unauthorized when missing Authorization header."""
    base_url, _db_file = admin_test_env

    # 1. List route without token
    status, _headers, body, _raw = api_request_with_raw(f"{base_url}/api/admin/plants")
    assert status == 401, f"Expected 401 on list without token, got {status}: {body}"
    assert body.get("detail") == "Missing or invalid Bearer token"

    # 2. Detail route without token
    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_demo_membrane"
    )
    assert status == 401, f"Expected 401 on detail without token, got {status}: {body}"
    assert body.get("detail") == "Missing or invalid Bearer token"


def test_admin_plants_200_with_token_on_both_routes(admin_test_env):
    """Admin read routes return 200 OK with correct Bearer token."""
    base_url, _db_file = admin_test_env
    auth_header = {"Authorization": "Bearer valid_test_admin_token_1234567890_32char"}

    # 1. List route with token
    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
    )
    assert status == 200, f"Expected 200 on list with token, got {status}: {body}"
    assert isinstance(body, list)

    # 2. Detail route with token
    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_demo_membrane",
        headers=auth_header,
    )
    assert status == 200, f"Expected 200 on detail with token, got {status}: {body}"
    assert isinstance(body, dict)
    assert body.get("plant_id") == "plant_demo_membrane"


def test_admin_plants_detail_404_for_unknown_plant_id(admin_test_env):
    """Admin detail route returns 404 for an unknown plant_id."""
    base_url, _db_file = admin_test_env
    auth_header = {"Authorization": "Bearer valid_test_admin_token_1234567890_32char"}

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/nonexistent_plant_xyz",
        headers=auth_header,
    )
    assert status == 404, f"Expected 404 for unknown plant, got {status}: {body}"
    assert body.get("detail") == "Plant 'nonexistent_plant_xyz' not found"


def test_admin_plants_list_contains_both_seeded_plants(admin_test_env):
    """Admin list route contains both seeded plants (membrane and water district 9)."""
    base_url, _db_file = admin_test_env
    auth_header = {"Authorization": "Bearer valid_test_admin_token_1234567890_32char"}

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
    )
    assert status == 200, f"Expected 200 on list, got {status}: {body}"
    assert isinstance(body, list)

    plant_ids = {p["plant_id"] for p in body}
    assert "plant_demo_membrane" in plant_ids, (
        f"plant_demo_membrane missing from {plant_ids}"
    )
    assert "plant_water_district_9" in plant_ids, (
        f"plant_water_district_9 missing from {plant_ids}"
    )

    plants_by_id = {p["plant_id"]: p for p in body}
    assert (
        plants_by_id["plant_demo_membrane"]["name"]
        == "Membrane Manufacturing Facility 01"
    )
    assert (
        plants_by_id["plant_water_district_9"]["name"]
        == "District 9 Water Booster Station"
    )


def test_admin_plants_detail_contains_areas_machines_signals_and_device_usernames(
    admin_test_env,
):
    """Admin detail route returns full structure with areas, machines, signals, and device usernames."""
    base_url, _db_file = admin_test_env
    auth_header = {"Authorization": "Bearer valid_test_admin_token_1234567890_32char"}

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_demo_membrane",
        headers=auth_header,
    )
    assert status == 200, f"Expected 200 on detail, got {status}: {body}"
    assert body["plant_id"] == "plant_demo_membrane"
    assert body["name"] == "Membrane Manufacturing Facility 01"
    assert body["timezone"] == "America/Chicago"

    # Areas check
    areas = body.get("areas")
    assert isinstance(areas, list) and len(areas) > 0, "Expected non-empty areas list"
    area_codes = [a["area_code"] for a in areas]
    assert "housing" in area_codes

    # Machines and signals check
    housing_area = next(a for a in areas if a["area_code"] == "housing")
    machines = housing_area.get("machines")
    assert isinstance(machines, list) and len(machines) > 0, (
        "Expected machines in housing area"
    )
    m_01 = next(m for m in machines if m["machine_code"] == "hm_01")
    signals = m_01.get("signals")
    assert isinstance(signals, list) and len(signals) > 0, "Expected signals in hm_01"
    signal_codes = [s["signal_code"] for s in signals]
    assert "mold_temperature_actual" in signal_codes

    # Device usernames check
    device_usernames = body.get("device_usernames")
    assert isinstance(device_usernames, list), "Expected device_usernames list"
    assert "device_plant_demo_membrane" in device_usernames


def test_admin_plants_response_bodies_never_contain_credentials_or_tokens(
    admin_test_env,
):
    """Response bodies never contain viewer_token, viewer_token_hash, password, or password_hash in keys or raw values."""
    base_url, db_file = admin_test_env
    auth_header = {"Authorization": "Bearer valid_test_admin_token_1234567890_32char"}

    # Seed a custom canary plant with explicit known secrets to verify they never leak
    canary_token_secret = "canary_viewer_token_SECRET_777"
    canary_token_hash = "canary_viewer_token_HASH_888"
    canary_password_hash = "canary_device_password_HASH_999"

    conn = get_db_connection(str(db_file))
    try:
        conn.execute(
            """
            INSERT INTO plants (id, name, timezone, viewer_token_hash)
            VALUES (%s, %s, %s, %s);
            """,
            ("plant_canary", "Canary Plant Facility", "UTC", canary_token_hash),
        )
        conn.execute(
            """
            INSERT INTO plant_credentials (plant_id, username, client_id, password_hash, is_active)
            VALUES (%s, %s, %s, %s, TRUE);
            """,
            (
                "plant_canary",
                "canary_device_user",
                "canary_client_id",
                canary_password_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # 1. Test List Endpoint
    status, _headers, body_list, raw_list = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
    )
    assert status == 200

    # Key check: ensure no sensitive keys exist anywhere in the JSON structure
    assert_no_sensitive_keys(body_list)

    # Raw string check: ensure secret values and sensitive keys never appear in raw text
    secret_values = [
        canary_token_secret,
        canary_token_hash,
        canary_password_hash,
        "demo_membrane_secure_token_123",
        "water_district_edge_key_771",
    ]
    forbidden_key_tokens = [
        '"viewer_token":',
        '"viewer_token_hash"',
        '"password":',
        '"password_hash"',
    ]
    for secret in secret_values:
        assert secret not in raw_list, (
            f"Secret value '{secret}' leaked in list raw response"
        )
    for key_pattern in forbidden_key_tokens:
        assert key_pattern not in raw_list, (
            f"Forbidden key pattern '{key_pattern}' found in list raw response"
        )

    # 2. Test Detail Endpoint for Canary Plant
    status, _headers, body_canary, raw_canary = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_canary",
        headers=auth_header,
    )
    assert status == 200
    assert_no_sensitive_keys(body_canary)
    for secret in secret_values:
        assert secret not in raw_canary, (
            f"Secret value '{secret}' leaked in canary detail raw response"
        )
    for key_pattern in forbidden_key_tokens:
        assert key_pattern not in raw_canary, (
            f"Forbidden key pattern '{key_pattern}' found in canary detail raw response"
        )

    # 3. Test Detail Endpoint for Seeded Plants (Membrane and Water)
    for p_id in ("plant_demo_membrane", "plant_water_district_9"):
        status, _headers, body_p, raw_p = api_request_with_raw(
            f"{base_url}/api/admin/plants/{p_id}",
            headers=auth_header,
        )
        assert status == 200
        assert_no_sensitive_keys(body_p)
        for secret in secret_values:
            assert secret not in raw_p, (
                f"Secret value '{secret}' leaked in {p_id} detail raw response"
            )
        for key_pattern in forbidden_key_tokens:
            assert key_pattern not in raw_p, (
                f"Forbidden key pattern '{key_pattern}' found in {p_id} detail raw response"
            )


def test_admin_plants_plant_with_no_viewer_token_reports_has_viewer_token_false(
    admin_test_env,
):
    """A plant with no viewer token reports has_viewer_token=false; plant with token reports true."""
    base_url, _db_file = admin_test_env
    auth_header = {"Authorization": "Bearer valid_test_admin_token_1234567890_32char"}

    # List check
    status, _headers, body_list, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
    )
    assert status == 200
    plants_by_id = {p["plant_id"]: p for p in body_list}
    assert plants_by_id["plant_demo_membrane"]["has_viewer_token"] is False
    assert plants_by_id["plant_water_district_9"]["has_viewer_token"] is True

    # Detail check: Membrane (no token)
    status, _headers, body_membrane, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_demo_membrane",
        headers=auth_header,
    )
    assert status == 200
    assert body_membrane["has_viewer_token"] is False

    # Detail check: Water District 9 (has token)
    status, _headers, body_water, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_water_district_9",
        headers=auth_header,
    )
    assert status == 200
    assert body_water["has_viewer_token"] is True
