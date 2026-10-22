import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from typing import Any

import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from admin_auth import admin_rate_limiter, viewer_rate_limiter
from db import get_db_connection
from main import (
    PLANTS_DIR,
    build_app,
    init_platform_db,
    seed_plants_if_empty,
)

# Generate test RSA keypair
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PRIVATE_KEY_PEM = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")

TEST_PUBLIC_KEY_PEM = (
    _private_key.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode("utf-8")
)

TEST_ISSUER = "https://clerk.plantpulse.test"
TEST_AUTHORIZED_PARTY = "http://localhost:3000"
STATIC_ADMIN_TOKEN = "valid_test_admin_token_1234567890_32char"


def mint_user_jwt(
    sub: str = "user_alice_123",
    role: str | None = None,
    plant_id: str | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "iss": TEST_ISSUER,
        "azp": TEST_AUTHORIZED_PARTY,
        "iat": now,
        "nbf": now - 10,
        "exp": now + 3600,
    }
    if role or plant_id:
        metadata: dict[str, Any] = {}
        if role:
            metadata["role"] = role
        if plant_id:
            metadata["plant_id"] = plant_id
        payload["metadata"] = metadata
    return jwt.encode(payload, key=TEST_PRIVATE_KEY_PEM, algorithm="RS256")


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
) -> tuple[int, dict[str, str], Any]:
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
            return resp.status, resp_headers, parsed
    except urllib.error.HTTPError as exc:
        resp_headers = {k.lower(): v for k, v in exc.headers.items()}
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = {"detail": raw}
        return exc.code, resp_headers, parsed


def make_plant_payload(plant_id: str, name: str = "Test Solar Plant") -> dict[str, Any]:
    return {
        "plant_id": plant_id,
        "name": name,
        "timezone": "UTC",
        "areas": [
            {
                "area_code": "area_01",
                "name": "Assembly",
                "display_order": 1,
                "machines": [
                    {
                        "machine_code": "press_01",
                        "name": "Hydraulic Press",
                        "machine_type": "press",
                        "display_order": 1,
                        "signals": [
                            {
                                "signal_code": "pressure_bar",
                                "name": "Pressure",
                                "unit": "bar",
                                "data_type": "float",
                                "is_setpoint": False,
                                "normal_min": 10.0,
                                "normal_max": 20.0,
                                "warn_min": 8.0,
                                "warn_max": 22.0,
                                "alarm_min": 5.0,
                                "alarm_max": 25.0,
                                "display_order": 1,
                            }
                        ],
                    }
                ],
            }
        ],
    }


@pytest.fixture
def owner_routes_server(monkeypatch):
    monkeypatch.setenv(
        "MOUNT_ADMIN_ENDPOINTS", "false"
    )  # Verify /api/me works even when admin is unmounted!
    monkeypatch.setenv("ADMIN_TOKEN", STATIC_ADMIN_TOKEN)
    monkeypatch.setenv("CLERK_PEM_PUBLIC_KEY", TEST_PUBLIC_KEY_PEM)
    monkeypatch.setenv("CLERK_ISSUER", TEST_ISSUER)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", TEST_AUTHORIZED_PARTY)

    admin_rate_limiter.reset()
    viewer_rate_limiter.reset()

    init_platform_db()
    conn = get_db_connection()
    try:
        seed_plants_if_empty(conn, PLANTS_DIR)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM plants WHERE id NOT IN ('plant_demo_membrane', 'plant_water_district_9');"
        )
        conn.commit()
    finally:
        conn.close()

    app = build_app(mount_admin=False)
    srv, thread, base_url = run_test_server(app)
    try:
        yield base_url
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM plants WHERE id NOT IN ('plant_demo_membrane', 'plant_water_district_9');"
            )
            conn.commit()
        finally:
            conn.close()


def test_owner_deletes_own_plant_and_quota_is_freed(owner_routes_server):
    """1. Owner deletes own plant; quota is freed and new plant can be created."""
    token = mint_user_jwt(sub="user_delete_tester")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Create 3 plants (quota max)
    for i in range(1, 4):
        payload = make_plant_payload(f"plant_del_quota_{i}", f"Plant {i}")
        status, _, _ = api_request(
            f"{owner_routes_server}/api/me/plants",
            headers=headers,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
        )
        assert status == 201

    # 4th plant fails with 409
    p4 = make_plant_payload("plant_del_quota_4", "Plant 4")
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants",
        headers=headers,
        method="POST",
        data=json.dumps(p4).encode("utf-8"),
    )
    assert status == 409

    # Owner deletes plant 1 via DELETE /api/me/plants/plant_del_quota_1
    status, _, del_resp = api_request(
        f"{owner_routes_server}/api/me/plants/plant_del_quota_1",
        headers={"Authorization": f"Bearer {token}"},
        method="DELETE",
    )
    assert status == 200
    assert del_resp.get("status") == "deleted"
    assert del_resp.get("plant_id") == "plant_del_quota_1"

    # Now creating plant 4 succeeds because quota was freed
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants",
        headers=headers,
        method="POST",
        data=json.dumps(p4).encode("utf-8"),
    )
    assert status == 201


def test_non_owner_cannot_delete_or_rotate(owner_routes_server):
    """2. Non-owner (authenticated as Bob) receives 404 on Alice's plant operations."""
    alice_token = mint_user_jwt(sub="user_alice_own")
    bob_token = mint_user_jwt(sub="user_bob_intruder")

    # Alice creates plant
    payload = make_plant_payload("plant_alice_lock", "Alice Secured")
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201

    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # Bob GET detail -> 404
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants/plant_alice_lock",
        headers=bob_headers,
        method="GET",
    )
    assert status == 404

    # Bob rotate credentials -> 404
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants/plant_alice_lock/credentials/rotate",
        headers=bob_headers,
        method="POST",
    )
    assert status == 404

    # Bob rotate viewer-token -> 404
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants/plant_alice_lock/viewer-token/rotate",
        headers=bob_headers,
        method="POST",
    )
    assert status == 404

    # Bob delete -> 404
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants/plant_alice_lock",
        headers=bob_headers,
        method="DELETE",
    )
    assert status == 404


def test_platform_admin_can_manage_owner_plant(owner_routes_server):
    """3. Platform admin can GET detail, rotate credentials, rotate viewer token, and DELETE via /api/me."""
    alice_token = mint_user_jwt(sub="user_alice_adm")
    admin_token = mint_user_jwt(sub="user_superadmin", role="platform_admin")

    # Alice creates plant
    payload = make_plant_payload("plant_alice_managed", "Alice Managed")
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {alice_token}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201

    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin GET detail -> 200
    status, _, detail = api_request(
        f"{owner_routes_server}/api/me/plants/plant_alice_managed",
        headers=admin_headers,
        method="GET",
    )
    assert status == 200
    assert detail["plant_id"] == "plant_alice_managed"

    # Admin rotate credentials -> 200
    status, resp_headers, creds = api_request(
        f"{owner_routes_server}/api/me/plants/plant_alice_managed/credentials/rotate",
        headers=admin_headers,
        method="POST",
    )
    assert status == 200
    assert "password" in creds
    assert "no-store" in resp_headers.get("cache-control", "")

    # Admin rotate viewer-token -> 200
    status, resp_headers, vtok = api_request(
        f"{owner_routes_server}/api/me/plants/plant_alice_managed/viewer-token/rotate",
        headers=admin_headers,
        method="POST",
    )
    assert status == 200
    assert "viewer_token" in vtok
    assert "no-store" in resp_headers.get("cache-control", "")

    # Admin DELETE -> 200
    status, _, del_resp = api_request(
        f"{owner_routes_server}/api/me/plants/plant_alice_managed",
        headers=admin_headers,
        method="DELETE",
    )
    assert status == 200
    assert del_resp.get("status") == "deleted"


def test_viewer_token_rotate_invalidates_old_token(owner_routes_server):
    """4. Viewer token rotate returns new token once, invalidates old token immediately."""
    token = mint_user_jwt(sub="user_vtok_rotate")
    payload = make_plant_payload("plant_vtok_rot", "VTok Rotate Plant")

    # Create plant and capture initial viewer token
    status, _, create_data = api_request(
        f"{owner_routes_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201
    old_token = create_data.get("one_time_viewer_token") or create_data.get(
        "viewer_token"
    )
    assert old_token is not None

    # Verify old token works anonymously on /machines/latest
    status, _, _ = api_request(
        f"{owner_routes_server}/api/plants/plant_vtok_rot/machines/latest",
        headers={"Authorization": f"Bearer {old_token}"},
        method="GET",
    )
    assert status == 200

    # Rotate viewer token
    status, resp_headers, rot_data = api_request(
        f"{owner_routes_server}/api/me/plants/plant_vtok_rot/viewer-token/rotate",
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    assert status == 200
    new_token = rot_data.get("viewer_token")
    assert new_token is not None
    assert new_token != old_token
    assert "no-store" in resp_headers.get("cache-control", "")

    # Old token now returns 401
    status, _, _ = api_request(
        f"{owner_routes_server}/api/plants/plant_vtok_rot/machines/latest",
        headers={"Authorization": f"Bearer {old_token}"},
        method="GET",
    )
    assert status == 401

    # New token returns 200
    status, _, _ = api_request(
        f"{owner_routes_server}/api/plants/plant_vtok_rot/machines/latest",
        headers={"Authorization": f"Bearer {new_token}"},
        method="GET",
    )
    assert status == 200


def test_device_credential_rotate_returns_new_password(owner_routes_server):
    """5. Device credential rotate returns new password once with Cache-Control: no-store."""
    token = mint_user_jwt(sub="user_cred_rot")
    payload = make_plant_payload("plant_cred_rot", "Cred Rotate Plant")

    status, _, create_data = api_request(
        f"{owner_routes_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201
    initial_creds = create_data.get("one_time_device_credentials", [])
    assert len(initial_creds) > 0
    old_password = initial_creds[0].get("password")

    # Rotate credentials
    status, resp_headers, rot_data = api_request(
        f"{owner_routes_server}/api/me/plants/plant_cred_rot/credentials/rotate",
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    assert status == 200
    new_password = rot_data.get("password")
    assert new_password is not None
    assert new_password != old_password
    assert "no-store" in resp_headers.get("cache-control", "")
    assert rot_data.get("plant_id") == "plant_cred_rot"


def test_demo_plants_cannot_be_deleted_via_me(owner_routes_server):
    """6. Demo and system plants cannot be deleted via /api/me."""
    admin_token = mint_user_jwt(sub="user_admin_demo_del", role="platform_admin")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Attempt to delete demo plant -> 403
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants/plant_demo_membrane",
        headers=headers,
        method="DELETE",
    )
    assert status == 403

    # Attempt to delete water plant -> 403
    status, _, _ = api_request(
        f"{owner_routes_server}/api/me/plants/plant_water_district_9",
        headers=headers,
        method="DELETE",
    )
    assert status == 403
