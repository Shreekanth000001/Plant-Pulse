import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing

import pytest
import uvicorn

from admin_auth import admin_rate_limiter
from db import get_db_connection
from main import build_app, init_platform_db, seed_plants_if_empty
from plant_definitions import load_plants_from_db


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


def api_request(
    url: str,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
) -> tuple[int, dict[str, str], dict]:
    req_headers = {"User-Agent": "test-runner"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read().decode("utf-8")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body}
            return resp.status, resp_headers, parsed
    except urllib.error.HTTPError as exc:
        resp_headers = {k.lower(): v for k, v in exc.headers.items()}
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = {"detail": body}
        return exc.code, resp_headers, parsed


def test_admin_routes_404_when_unmounted_by_default(monkeypatch):
    """Admin routes return 404 when MOUNT_ADMIN_ENDPOINTS is not set or false."""
    monkeypatch.delenv("MOUNT_ADMIN_ENDPOINTS", raising=False)
    app = build_app()
    srv, thread, base_url = run_test_server(app)
    try:
        status, _headers, body = api_request(f"{base_url}/api/admin/health")
        assert status == 404, (
            f"Expected 404 when unmounted by default, got {status}: {body}"
        )
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_admin_routes_503_when_admin_token_unset(monkeypatch):
    """Admin routes return 503 when mounted but ADMIN_TOKEN environment variable is unset."""
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    admin_rate_limiter.reset()

    app = build_app()
    srv, thread, base_url = run_test_server(app)
    try:
        status, _headers, body = api_request(
            f"{base_url}/api/admin/health",
            headers={"Authorization": "Bearer some_token"},
        )
        assert status == 503, (
            f"Expected 503 when ADMIN_TOKEN unset, got {status}: {body}"
        )
        assert "ADMIN_TOKEN" in body.get("detail", "")
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_admin_routes_401_on_missing_and_malformed_header(monkeypatch):
    """Admin routes return 401 on missing or malformed Authorization header (not 422)."""
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "super_secret_admin_token_123")
    admin_rate_limiter.reset()

    app = build_app()
    srv, thread, base_url = run_test_server(app)
    try:
        # 1. Missing Authorization header completely -> must be 401, NOT 422
        status, _headers, body = api_request(f"{base_url}/api/admin/health")
        assert status == 401, f"Expected 401 on missing header, got {status}: {body}"
        assert body.get("detail") == "Missing or invalid Bearer token"

        # 2. Malformed header: Basic auth -> 401
        status, _headers, body = api_request(
            f"{base_url}/api/admin/health",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert status == 401, f"Expected 401 on Basic auth, got {status}: {body}"

        # 3. Malformed header: Bearer prefix with empty token -> 401
        status, _headers, body = api_request(
            f"{base_url}/api/admin/health",
            headers={"Authorization": "Bearer "},
        )
        assert status == 401, f"Expected 401 on empty token, got {status}: {body}"

        # 4. Wrong bearer token -> 401
        status, _headers, body = api_request(
            f"{base_url}/api/admin/health",
            headers={"Authorization": "Bearer wrong_token_xyz"},
        )
        assert status == 401, f"Expected 401 on wrong token, got {status}: {body}"
        assert body.get("detail") == "Invalid admin token"
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_admin_routes_200_with_correct_token(monkeypatch):
    """Admin routes return 200 with correct Bearer token."""
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "correct_admin_token_xyz")
    admin_rate_limiter.reset()

    app = build_app()
    srv, thread, base_url = run_test_server(app)
    try:
        status, _headers, body = api_request(
            f"{base_url}/api/admin/health",
            headers={"Authorization": "Bearer correct_admin_token_xyz"},
        )
        assert status == 200, f"Expected 200 with correct token, got {status}: {body}"
        assert body.get("status") == "ok"
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_admin_routes_throttle_after_5_wrong_attempts_with_retry_after(monkeypatch):
    """6th wrong attempt returns 429 with Retry-After header and lockout check runs before compare."""
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "valid_secret_admin_token")
    admin_rate_limiter.reset()

    app = build_app()
    srv, thread, base_url = run_test_server(app)
    try:
        # 5 wrong attempts -> all return 401
        for i in range(1, 6):
            status, headers, body = api_request(
                f"{base_url}/api/admin/health",
                headers={"Authorization": f"Bearer wrong_token_attempt_{i}"},
            )
            assert status == 401, f"Attempt {i} expected 401, got {status}: {body}"

        # 6th attempt: even if the client supplies the CORRECT token now,
        # the lockout check runs BEFORE the compare and returns 429!
        status, headers, body = api_request(
            f"{base_url}/api/admin/health",
            headers={"Authorization": "Bearer valid_secret_admin_token"},
        )
        assert status == 429, f"6th attempt expected 429, got {status}: {body}"
        assert "retry-after" in headers, "Expected Retry-After header in 429 response"
        retry_after = int(headers["retry-after"])
        assert retry_after > 0, f"Expected positive Retry-After, got {retry_after}"
        assert "Locked out" in body.get("detail", "")
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_admin_routes_throttle_malformed_headers_count_as_failures(monkeypatch):
    """5 malformed Authorization headers count as failures and trigger 429 on the 6th attempt."""
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "valid_secret_admin_token")
    admin_rate_limiter.reset()

    app = build_app()
    srv, thread, base_url = run_test_server(app)
    try:
        malformed_headers = [
            "Basic dXNlcjpwYXNz",
            "Bearer ",
            "InvalidScheme 12345",
            "Bearer   ",
            "Token xyz",
        ]
        # 5 malformed attempts -> all return 401 and increment failures
        for i, header_val in enumerate(malformed_headers, 1):
            status, _headers, body = api_request(
                f"{base_url}/api/admin/health",
                headers={"Authorization": header_val},
            )
            assert status == 401, f"Attempt {i} expected 401, got {status}: {body}"

        # 6th attempt: lockout check runs BEFORE compare and returns 429
        status, headers, body = api_request(
            f"{base_url}/api/admin/health",
            headers={"Authorization": "Bearer valid_secret_admin_token"},
        )
        assert status == 429, (
            f"6th attempt after malformed headers expected 429, got {status}: {body}"
        )
        assert "retry-after" in headers, "Expected Retry-After header in 429 response"
        retry_after = int(headers["retry-after"])
        assert retry_after > 0, f"Expected positive Retry-After, got {retry_after}"
        assert "Locked out" in body.get("detail", "")
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_seed_runs_only_on_empty_db_and_ignores_changed_json(tmp_path):
    """Seed runs only on an empty database; subsequent starts ignore modified JSON and never write back."""
    db_file = tmp_path / "test_platform.db"
    init_platform_db(db_file)

    # Prepare a temporary plants directory with 1 plant
    plants_dir = tmp_path / "plants"
    plants_dir.mkdir()
    plant_json = plants_dir / "plant_alpha.json"
    initial_content = {
        "plant_id": "plant_alpha",
        "name": "Alpha Plant Original Name",
        "timezone": "UTC",
        "viewer_token": "alpha_token_123",
        "mqtt_credentials": [],
        "areas": [
            {
                "area_code": "area_1",
                "name": "Area One",
                "display_order": 1,
                "machines": [
                    {
                        "machine_code": "m_1",
                        "name": "Machine One",
                        "machine_type": "standard",
                        "display_order": 1,
                        "signals": [
                            {
                                "signal_code": "sig_temp",
                                "name": "Temperature",
                                "unit": "C",
                                "data_type": "float",
                                "display_order": 1,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    plant_json.write_text(json.dumps(initial_content), encoding="utf-8")
    initial_mtime = plant_json.stat().st_mtime_ns

    # First run: DB is empty -> seed_plants_if_empty seeds DB
    conn = get_db_connection(db_file)
    try:
        seeded = seed_plants_if_empty(conn, plants_dir)
        assert seeded is True, "Expected initial run on empty DB to seed"
        cur = conn.cursor()
        cur.execute("SELECT name FROM plants WHERE id = 'plant_alpha';")
        row = cur.fetchone()
        assert row is not None
        assert row["name"] == "Alpha Plant Original Name"
    finally:
        conn.close()

    assert plant_json.stat().st_mtime_ns == initial_mtime, (
        "Initial seed must never modify or rewrite JSON files"
    )

    # Modify the JSON file on disk and add a second plant JSON
    modified_content = dict(initial_content)
    modified_content["name"] = "MODIFIED Alpha Plant Name"
    plant_json.write_text(json.dumps(modified_content), encoding="utf-8")

    new_plant_json = plants_dir / "plant_beta.json"
    new_plant_json.write_text(
        json.dumps(
            {
                "plant_id": "plant_beta",
                "name": "Beta Plant New",
                "timezone": "UTC",
                "viewer_token": None,
                "mqtt_credentials": [],
                "areas": [],
            }
        ),
        encoding="utf-8",
    )

    # Second run: DB is NOT empty -> seed_plants_if_empty must NOT run and ignore changes
    conn2 = get_db_connection(db_file)
    try:
        seeded2 = seed_plants_if_empty(conn2, plants_dir)
        assert seeded2 is False, "Expected seed to skip when DB is not empty"

        # Load plants from DB
        db_plants = load_plants_from_db(conn2)
        assert "plant_alpha" in db_plants
        assert db_plants["plant_alpha"].name == "Alpha Plant Original Name", (
            "DB plant name must remain original; modified JSON must be ignored"
        )
        assert "plant_beta" not in db_plants, (
            "New JSON plant must not be imported into non-empty DB"
        )

        cur2 = conn2.cursor()
        cur2.execute("SELECT COUNT(*) FROM plants;")
        assert cur2.fetchone()[0] == 1, (
            "Only the initially seeded plant should exist in DB"
        )
    finally:
        conn2.close()

    # Ensure application never writes back to JSON files
    # The JSON files on disk should not be overwritten by DB state
    assert json.loads(new_plant_json.read_text())["plant_id"] == "plant_beta"
