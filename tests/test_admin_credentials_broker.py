import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from typing import Any
from unittest.mock import patch

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
from scripts.generate_mosquitto_auth import hash_password_pbkdf2


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
def admin_credentials_env(tmp_path, monkeypatch):
    db_file = tmp_path / "platform.db"
    auth_dir = tmp_path / "mosquitto_auth"
    auth_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PLATFORM_DB_PATH", str(db_file))
    monkeypatch.setattr("main.PLATFORM_DB_PATH", str(db_file))
    monkeypatch.setenv("MOSQUITTO_AUTH_DIR", str(auth_dir))
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "valid_test_admin_token_1234567890_32char")
    monkeypatch.setenv("BACKEND_MQTT_USER", "backend_service")
    monkeypatch.setenv("BACKEND_MQTT_PASSWORD", "backend_secret_pass_123")
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
        yield base_url, db_file, auth_dir, port
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)
        from main import viewer_tracker

        viewer_tracker._last_poll_at = None


def sample_plant_payload_no_creds(plant_id: str = "plant_nocred_01"):
    return {
        "plant_id": plant_id,
        "name": f"Plant Without Creds {plant_id}",
        "timezone": "UTC",
        "enabled_modules": ["core", "alarms"],
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
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_admin_create_plant_generates_and_returns_credential_once(
    admin_credentials_env,
):
    """POST /api/admin/plants without credentials generates and returns one_time_device_credentials."""
    base_url, db_file, _auth_dir, _port = admin_credentials_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    payload = sample_plant_payload_no_creds("plant_autocred_test")

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201, f"Expected 201, got {status}: {body}"
    assert "one_time_device_credentials" in body
    creds = body["one_time_device_credentials"]
    assert len(creds) == 1
    assert creds[0]["username"] == "device_plant_autocred_test"
    generated_pass = creds[0]["password"]
    assert len(generated_pass) >= 20

    # Verify DB stored the hash, not the plaintext
    conn = get_db_connection(str(db_file))
    cur = conn.cursor()
    cur.execute(
        "SELECT password_hash FROM plant_credentials WHERE plant_id = 'plant_autocred_test' AND username = 'device_plant_autocred_test';"
    )
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row["password_hash"].startswith("$7$101$")
    assert generated_pass not in row["password_hash"]

    # Verify subsequent GET detail never returns the password
    get_status, _gh, get_body, get_raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_autocred_test",
        headers=auth_header,
        method="GET",
    )
    assert get_status == 200
    assert "one_time_device_credentials" not in get_body
    assert generated_pass not in get_raw


def test_admin_create_plant_response_cache_control_no_store(admin_credentials_env):
    """POST /api/admin/plants response must send Cache-Control: no-store header."""
    base_url, _db_file, _auth_dir, _port = admin_credentials_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    payload = sample_plant_payload_no_creds("plant_cache_hdr_test")

    status, headers, _body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201
    cache_control = headers.get("cache-control", "").lower()
    assert "no-store" in cache_control, (
        f"Expected 'no-store' in Cache-Control, got: {cache_control}"
    )


def test_admin_rotate_credentials_updates_db_and_returns_new_secret(
    admin_credentials_env,
):
    """POST /api/admin/plants/{plant_id}/credentials/rotate updates DB hash and returns new secret with no-store."""
    base_url, db_file, _auth_dir, _port = admin_credentials_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    # Create plant
    payload = sample_plant_payload_no_creds("plant_rot_check")
    api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )

    # Initial hash
    conn = get_db_connection(str(db_file))
    cur = conn.cursor()
    cur.execute(
        "SELECT password_hash FROM plant_credentials WHERE plant_id = 'plant_rot_check';"
    )
    initial_hash = cur.fetchone()["password_hash"]
    conn.close()

    # Call rotation endpoint
    status, headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_rot_check/credentials/rotate",
        headers=auth_header,
        method="POST",
    )
    assert status == 200, f"Expected 200, got {status}: {body}"
    assert body.get("plant_id") == "plant_rot_check"
    assert body.get("username") == "device_plant_rot_check"
    new_password = body.get("password")
    assert len(new_password) >= 20
    assert "broker_reloaded" in body

    # Header check
    cache_control = headers.get("cache-control", "").lower()
    assert "no-store" in cache_control

    # DB check
    conn2 = get_db_connection(str(db_file))
    cur2 = conn2.cursor()
    cur2.execute(
        "SELECT password_hash FROM plant_credentials WHERE plant_id = 'plant_rot_check';"
    )
    rotated_hash = cur2.fetchone()["password_hash"]
    conn2.close()
    assert rotated_hash != initial_hash
    assert rotated_hash.startswith("$7$101$")
    assert new_password not in rotated_hash


def test_admin_rotate_credentials_404_for_unknown_plant(admin_credentials_env):
    """POST /api/admin/plants/{plant_id}/credentials/rotate returns 404 for unknown plant_id."""
    base_url, _db_file, _auth_dir, _port = admin_credentials_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/non_existent_plant_xyz/credentials/rotate",
        headers=auth_header,
        method="POST",
    )
    assert status == 404
    assert "not found" in str(body).lower()


def test_admin_password_never_appears_in_captured_logs_during_create_and_rotate(
    admin_credentials_env, caplog
):
    """Plaintext password generated during create and rotate must never appear in server logs."""
    base_url, _db_file, _auth_dir, _port = admin_credentials_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }

    # Setup log capturing
    caplog.set_level(logging.DEBUG)

    # 1. Create plant
    payload = sample_plant_payload_no_creds("plant_log_scrub_test")
    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201
    created_pass = body["one_time_device_credentials"][0]["password"]

    # 2. Rotate credentials
    rot_status, _rh, rot_body, _rr = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_log_scrub_test/credentials/rotate",
        headers=auth_header,
        method="POST",
    )
    assert rot_status == 200
    rotated_pass = rot_body["password"]

    # Check all captured log records
    all_logs = caplog.text
    assert created_pass not in all_logs, "Created plaintext password leaked in logs!"
    assert rotated_pass not in all_logs, "Rotated plaintext password leaked in logs!"


def test_auth_files_atomic_replace_preserves_old_files_on_hashing_error(tmp_path):
    """If an error occurs during auth generation/hashing, destination files are left untouched."""
    from scripts.generate_mosquitto_auth import sync_broker_auth_from_db

    db_file = tmp_path / "test_atomic.db"
    init_platform_db(db_file)
    conn = get_db_connection(str(db_file))
    seed_plants_if_empty(conn, PLANTS_DIR)

    auth_dir = tmp_path / "auth_atomic"
    auth_dir.mkdir(parents=True, exist_ok=True)
    passwd_path = auth_dir / "passwd"
    acl_path = auth_dir / "acl.conf"

    # Initial successful sync
    sync_broker_auth_from_db(conn, auth_dir=auth_dir, reload=False)
    initial_passwd = passwd_path.read_text(encoding="utf-8")
    initial_acl = acl_path.read_text(encoding="utf-8")

    # Insert an unhashed credential so sync must perform hashing
    conn.execute(
        """
        INSERT INTO plant_credentials (plant_id, username, client_id, password_hash, is_active)
        VALUES ('plant_demo_membrane', 'new_unhashed_user', 'new_client', 'plaintext_pwd_to_hash', 1);
        """
    )
    conn.commit()

    # Force a failure during hashing
    with (
        patch(
            "scripts.generate_mosquitto_auth.hash_password_pbkdf2",
            side_effect=RuntimeError("Hashing boom!"),
        ),
        pytest.raises(RuntimeError, match="Hashing boom!"),
    ):
        sync_broker_auth_from_db(conn, auth_dir=auth_dir, reload=False)

    # Destination files must be completely intact
    assert passwd_path.read_text(encoding="utf-8") == initial_passwd
    assert acl_path.read_text(encoding="utf-8") == initial_acl


def test_generated_passwd_and_acl_always_contain_backend_user_even_with_empty_plants_table(
    tmp_path,
):
    """Generated passwd and acl.conf always contain backend user even with 0 plants in DB."""
    from scripts.generate_mosquitto_auth import sync_broker_auth_from_db

    db_file = tmp_path / "empty_plants.db"
    init_platform_db(db_file)
    conn = get_db_connection(str(db_file))

    # Plants table is completely empty
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM plants;")
    assert cur.fetchone()[0] == 0

    auth_dir = tmp_path / "auth_empty"
    sync_broker_auth_from_db(
        conn,
        auth_dir=auth_dir,
        backend_user="backend_service",
        backend_password="backend_password_abc",
        reload=False,
    )
    conn.close()

    passwd_content = (auth_dir / "passwd").read_text(encoding="utf-8")
    acl_content = (auth_dir / "acl.conf").read_text(encoding="utf-8")

    assert "backend_service:$7$101$" in passwd_content
    assert "user backend_service" in acl_content
    assert "topic readwrite plants/#" in acl_content


def test_auth_files_contain_no_plaintext_passwords(tmp_path):
    """Generated passwd file contains only $7$101$... hashes and no plaintext passwords."""
    from scripts.generate_mosquitto_auth import sync_broker_auth_from_db

    db_file = tmp_path / "test_plain.db"
    init_platform_db(db_file)
    conn = get_db_connection(str(db_file))
    seed_plants_if_empty(conn, PLANTS_DIR)

    canary = "plain_password_super_secret_999"
    conn.execute(
        """
        INSERT INTO plant_credentials (plant_id, username, client_id, password_hash, is_active)
        VALUES ('plant_demo_membrane', 'canary_user', 'canary_client', ?, 1)
        ON CONFLICT (plant_id, username) DO UPDATE SET password_hash = excluded.password_hash;
        """,
        (hash_password_pbkdf2(canary),),
    )
    conn.commit()

    auth_dir = tmp_path / "auth_plain"
    sync_broker_auth_from_db(conn, auth_dir=auth_dir, reload=False)
    conn.close()

    passwd_content = (auth_dir / "passwd").read_text(encoding="utf-8")
    assert canary not in passwd_content
    assert "canary_user:$7$101$" in passwd_content


def test_auth_files_plant_acl_isolation(tmp_path):
    """ACL file grants plant A only plants/plant_a/# and plant B only plants/plant_b/#."""
    from scripts.generate_mosquitto_auth import sync_broker_auth_from_db

    db_file = tmp_path / "test_iso.db"
    init_platform_db(db_file)
    conn = get_db_connection(str(db_file))
    seed_plants_if_empty(conn, PLANTS_DIR)

    auth_dir = tmp_path / "auth_iso"
    sync_broker_auth_from_db(conn, auth_dir=auth_dir, reload=False)
    conn.close()

    acl_content = (auth_dir / "acl.conf").read_text(encoding="utf-8")

    # demo membrane device has access to membrane only
    lines = acl_content.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "user device_plant_demo_membrane":
            next_line = lines[i + 1].strip()
            assert next_line == "topic readwrite plants/plant_demo_membrane/#"
        elif line.strip() == "user device_plant_water_district_9":
            next_line = lines[i + 1].strip()
            assert next_line == "topic readwrite plants/plant_water_district_9/#"


def test_admin_delete_plant_returns_200_with_broker_reloaded_false_when_reload_fails(
    admin_credentials_env, monkeypatch
):
    """When Mosquitto SIGHUP reload fails, DELETE returns 200 with broker_reloaded=false."""
    base_url, _db_file, _auth_dir, _port = admin_credentials_env
    auth_header = {
        "Authorization": "Bearer valid_test_admin_token_1234567890_32char",
        "Content-Type": "application/json",
    }
    # Create plant
    payload = sample_plant_payload_no_creds("plant_del_reload_fail")
    api_request_with_raw(
        f"{base_url}/api/admin/plants",
        headers=auth_header,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )

    # Monkeypatch reload to fail
    from scripts import generate_mosquitto_auth

    monkeypatch.setattr(generate_mosquitto_auth, "reload_mosquitto", lambda: False)

    status, _headers, body, _raw = api_request_with_raw(
        f"{base_url}/api/admin/plants/plant_del_reload_fail",
        headers=auth_header,
        method="DELETE",
    )
    assert status == 200
    assert body.get("status") == "deleted"
    assert body.get("broker_reloaded") is False


def test_admin_rotate_credentials_reuses_stored_password_hash_for_unchanged_credentials(
    tmp_path, monkeypatch
):
    """Regenerating auth files reuses stored password_hash for unchanged credentials without re-hashing."""
    from scripts.generate_mosquitto_auth import sync_broker_auth_from_db

    db_file = tmp_path / "test_reuse.db"
    init_platform_db(db_file)
    conn = get_db_connection(str(db_file))
    seed_plants_if_empty(conn, PLANTS_DIR)

    auth_dir = tmp_path / "auth_reuse"
    sync_broker_auth_from_db(conn, auth_dir=auth_dir, reload=False)

    passwd_1 = (auth_dir / "passwd").read_text(encoding="utf-8")

    # Count how many times hash_password_pbkdf2 is called when nothing changed
    hash_count = 0
    import scripts.generate_mosquitto_auth as gma

    orig_hash = gma.hash_password_pbkdf2

    def counting_hash(*args, **kwargs):
        nonlocal hash_count
        hash_count += 1
        return orig_hash(*args, **kwargs)

    monkeypatch.setattr(gma, "hash_password_pbkdf2", counting_hash)

    sync_broker_auth_from_db(conn, auth_dir=auth_dir, reload=False)
    conn.close()

    passwd_2 = (auth_dir / "passwd").read_text(encoding="utf-8")
    assert passwd_1 == passwd_2
    # Because all credentials in DB were already valid $7$ hashes, 0 device credentials needed re-hashing
    assert hash_count == 0, (
        f"Expected 0 rehashes for unchanged credentials, got {hash_count}"
    )
