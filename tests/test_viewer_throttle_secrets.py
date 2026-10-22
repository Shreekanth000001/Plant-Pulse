import hashlib
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

from admin_auth import admin_rate_limiter
from ingest import sync_plant_definitions
from main import app, viewer_rate_limiter
from plant_definitions import MQTTCredential, PlantDefinition, load_plants
from scripts.generate_mosquitto_auth import generate_auth_files

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"
WATER_TOKEN = "district9_read_secret_token_889"


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
        proxy_headers=False,
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


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    viewer_rate_limiter.reset()
    admin_rate_limiter.reset()
    yield
    viewer_rate_limiter.reset()
    admin_rate_limiter.reset()


def test_viewer_throttle_after_5_wrong_attempts_returns_429():
    """Criterion 1: 5 wrong bearer attempts return 401; 6th returns 429 with Retry-After header."""
    srv, thread, base_url = run_test_server(app)
    try:
        for i in range(1, 6):
            status, _headers, body = api_request(
                f"{base_url}/api/plants/plant_water_district_9/definition",
                headers={"Authorization": f"Bearer wrong_token_guess_{i}"},
            )
            assert status == 401, f"Attempt {i} expected 401, got {status}: {body}"

        status6, headers6, body6 = api_request(
            f"{base_url}/api/plants/plant_water_district_9/definition",
            headers={"Authorization": "Bearer wrong_token_guess_6"},
        )
        assert status6 == 429, f"6th attempt expected 429, got {status6}: {body6}"
        assert "retry-after" in headers6
        retry_after = int(headers6["retry-after"])
        assert retry_after > 0
        assert "Locked out" in body6.get("detail", "")
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_viewer_throttle_lockout_checked_before_compare():
    """Criterion 1: Lockout is evaluated before token comparison; sending correct token while locked out returns 429."""
    srv, thread, base_url = run_test_server(app)
    try:
        for i in range(1, 6):
            status, _, body = api_request(
                f"{base_url}/api/plants/plant_water_district_9/definition",
                headers={"Authorization": f"Bearer wrong_token_{i}"},
            )
            assert status == 401, f"Attempt {i} expected 401, got {status}: {body}"

        # 6th attempt with CORRECT token
        status_correct, headers_correct, body_correct = api_request(
            f"{base_url}/api/plants/plant_water_district_9/definition",
            headers={"Authorization": f"Bearer {WATER_TOKEN}"},
        )
        assert status_correct == 429, (
            f"Expected 429 on correct token while locked out, got {status_correct}: {body_correct}"
        )
        assert "retry-after" in headers_correct
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_viewer_throttle_malformed_headers_count():
    """Criterion 1: Malformed Authorization headers count as failures and trigger 429 on 6th attempt."""
    srv, thread, base_url = run_test_server(app)
    try:
        malformed_headers = [
            "Basic dXNlcjpwYXNz",
            "Bearer ",
            "InvalidScheme 12345",
            "Bearer   ",
            "Token xyz",
        ]
        for i, header_val in enumerate(malformed_headers, 1):
            status, _, body = api_request(
                f"{base_url}/api/plants/plant_water_district_9/definition",
                headers={"Authorization": header_val},
            )
            assert status == 401, (
                f"Malformed attempt {i} expected 401, got {status}: {body}"
            )

        # 6th attempt must be 429
        status6, headers6, _ = api_request(
            f"{base_url}/api/plants/plant_water_district_9/definition",
            headers={"Authorization": f"Bearer {WATER_TOKEN}"},
        )
        assert status6 == 429
        assert "retry-after" in headers6
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_viewer_throttle_ws_ticket_endpoint():
    """Criterion 1: POST /api/plants/{plant_id}/ws-ticket applies the same rate limiting on failed attempts."""
    srv, thread, base_url = run_test_server(app)
    try:
        for i in range(1, 6):
            status, _, body = api_request(
                f"{base_url}/api/plants/plant_water_district_9/ws-ticket",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer wrong_ticket_attempt_{i}",
                },
                method="POST",
                data=b"{}",
            )
            assert status == 401, (
                f"Ticket attempt {i} expected 401, got {status}: {body}"
            )

        status6, headers6, _ = api_request(
            f"{base_url}/api/plants/plant_water_district_9/ws-ticket",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {WATER_TOKEN}",
            },
            method="POST",
            data=b"{}",
        )
        assert status6 == 429
        assert "retry-after" in headers6
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_viewer_throttle_does_not_trust_x_forwarded_for():
    """Criterion 1: X-Forwarded-For is not trusted; rate limit bucket is keyed strictly by socket client.host."""
    srv, thread, base_url = run_test_server(app)
    try:
        for i in range(1, 6):
            status, _, _ = api_request(
                f"{base_url}/api/plants/plant_water_district_9/definition",
                headers={
                    "Authorization": f"Bearer wrong_{i}",
                    "X-Forwarded-For": f"198.51.100.{i}",
                },
            )
            assert status == 401

        status6, headers6, _ = api_request(
            f"{base_url}/api/plants/plant_water_district_9/definition",
            headers={
                "Authorization": f"Bearer {WATER_TOKEN}",
                "X-Forwarded-For": "203.0.113.199",
            },
        )
        assert status6 == 429
        assert "retry-after" in headers6
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_load_plants_reads_secrets_from_environment(monkeypatch):
    """Criterion 2: load_plants binds PLANT_<ID>_VIEWER_TOKEN and DEVICE_<USERNAME>_PASSWORD from env."""
    monkeypatch.setenv(
        "PLANT_WATER_DISTRICT_9_VIEWER_TOKEN", "env_loaded_water_token_999"
    )
    monkeypatch.setenv(
        "DEVICE_PLANT_WATER_DISTRICT_9_PASSWORD", "env_loaded_water_device_pass_888"
    )

    plants = load_plants(PLANTS_DIR)
    water_plant = plants["plant_water_district_9"]
    assert water_plant.viewer_token == "env_loaded_water_token_999"
    assert len(water_plant.mqtt_credentials) > 0
    assert (
        water_plant.mqtt_credentials[0].password == "env_loaded_water_device_pass_888"
    )


def test_plant_json_files_contain_no_secrets():
    """Criterion 2: plants/*.json files contain no passwords and viewer_token is null or absent."""
    for json_file in sorted(PLANTS_DIR.glob("*.json")):
        content = json_file.read_text(encoding="utf-8")
        data = json.loads(content)

        # Check raw string for password field
        assert '"password"' not in content, (
            f"Found raw 'password' field in {json_file.name}"
        )
        # Check parsed data
        viewer_token = data.get("viewer_token")
        assert viewer_token is None, (
            f"Expected viewer_token to be None in {json_file.name}, got {viewer_token}"
        )
        for cred in data.get("mqtt_credentials", []):
            assert "password" not in cred or cred["password"] is None, (
                f"Found password in mqtt_credentials in {json_file.name}"
            )


def test_sync_plant_definitions_preserves_existing_hashes():
    """Criterion 2 & 3: sync_plant_definitions with omitted secrets does not overwrite existing DB hashes."""
    from db import get_db_connection

    conn = get_db_connection()
    try:
        original_hash = hashlib.sha256(b"existing_secret_token").hexdigest()
        conn.execute(
            """
            INSERT INTO plants (id, name, timezone, viewer_token_hash)
            VALUES ('test_p1', 'Test Plant', 'UTC', %s)
            ON CONFLICT (id) DO UPDATE SET viewer_token_hash = excluded.viewer_token_hash;
            """,
            (original_hash,),
        )
        original_pwd_hash = "$7$101$salted$hash"
        conn.execute(
            """
            INSERT INTO plant_credentials (plant_id, username, client_id, password_hash)
            VALUES ('test_p1', 'user_1', 'c1', %s)
            ON CONFLICT (plant_id, username) DO UPDATE SET password_hash = excluded.password_hash;
            """,
            (original_pwd_hash,),
        )
        conn.commit()

        plant = PlantDefinition(
            plant_id="test_p1",
            name="Updated Plant Name",
            timezone="UTC",
            viewer_token=None,
            viewer_token_hash=None,
            mqtt_credentials=[
                MQTTCredential(username="user_1", client_id="c1", password=None)
            ],
            areas=[],
        )

        sync_plant_definitions(conn, {"test_p1": plant})

        cur = conn.cursor()
        cur.execute("SELECT name, viewer_token_hash FROM plants WHERE id = 'test_p1'")
        p_row = cur.fetchone()
        assert p_row["name"] == "Updated Plant Name"
        assert p_row["viewer_token_hash"] == original_hash, (
            f"viewer_token_hash was overwritten! Expected {original_hash}, got {p_row['viewer_token_hash']}"
        )

        cur.execute(
            "SELECT password_hash FROM plant_credentials WHERE plant_id = 'test_p1' AND username = 'user_1'"
        )
        c_row = cur.fetchone()
        assert c_row["password_hash"] == original_pwd_hash
    finally:
        conn.execute("DELETE FROM plants WHERE id = 'test_p1';")
        conn.commit()
        conn.close()


def test_auth_gen_missing_device_password_fails_closed(tmp_path, monkeypatch):
    """Criterion 4: Missing device password at Mosquitto auth generation raises ValueError (fails closed)."""
    monkeypatch.delenv("MQTT_PASSWORD", raising=False)
    monkeypatch.delenv("WATER_MQTT_PASSWORD", raising=False)
    monkeypatch.delenv("DEVICE_PLANT_DEMO_MEMBRANE_PASSWORD", raising=False)
    monkeypatch.delenv("DEVICE_PLANT_WATER_DISTRICT_9_PASSWORD", raising=False)

    fake_plants = tmp_path / "plants"
    fake_plants.mkdir()
    fake_json = fake_plants / "plant_mock.json"
    fake_json.write_text(
        json.dumps(
            {
                "plant_id": "plant_mock",
                "name": "Mock Plant",
                "timezone": "UTC",
                "viewer_token": None,
                "mqtt_credentials": [
                    {
                        "username": "device_mock",
                        "client_id": "client_mock",
                    }
                ],
                "areas": [],
            }
        ),
        encoding="utf-8",
    )

    passwd_path = tmp_path / "passwd"
    acl_path = tmp_path / "acl.conf"

    with pytest.raises(ValueError) as excinfo:
        generate_auth_files(
            plants_dir=fake_plants,
            passwd_path=passwd_path,
            acl_path=acl_path,
            backend_user="backend_service",
            backend_password="backend_password",
        )
    assert "Missing MQTT password" in str(excinfo.value)


def test_auth_gen_error_message_contains_no_secrets(tmp_path, monkeypatch):
    """Criterion 4: The error raised for missing password never leaks any secret or token in its text."""
    secret_viewer_token = "ultra_sensitive_token_777888"
    secret_backend_pass = "top_secret_backend_pass_999000"

    monkeypatch.setenv("PLANT_MOCK_VIEWER_TOKEN", secret_viewer_token)
    monkeypatch.delenv("DEVICE_MOCK_USER_PASSWORD", raising=False)

    fake_plants = tmp_path / "plants"
    fake_plants.mkdir()
    fake_json = fake_plants / "plant_mock.json"
    fake_json.write_text(
        json.dumps(
            {
                "plant_id": "plant_mock",
                "name": "Mock Plant",
                "timezone": "UTC",
                "viewer_token": None,
                "mqtt_credentials": [
                    {
                        "username": "mock_user",
                        "client_id": "mock_client",
                    }
                ],
                "areas": [],
            }
        ),
        encoding="utf-8",
    )

    try:
        generate_auth_files(
            plants_dir=fake_plants,
            passwd_path=tmp_path / "passwd",
            acl_path=tmp_path / "acl.conf",
            backend_user="backend_service",
            backend_password=secret_backend_pass,
        )
    except ValueError as exc:
        msg = str(exc)
        assert secret_viewer_token not in msg, (
            f"Found secret viewer token in error message! {msg}"
        )
        assert secret_backend_pass not in msg, (
            f"Found backend password in error message! {msg}"
        )
    else:
        pytest.fail("Expected generate_auth_files to raise ValueError")
