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
def ownership_server(monkeypatch):
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
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
        # Clean up any test plants from previous runs
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM plants WHERE id NOT IN ('plant_demo_membrane', 'plant_water_district_9');"
        )
        conn.commit()
    finally:
        conn.close()

    app = build_app(mount_admin=True)
    srv, thread, base_url = run_test_server(app)
    try:
        yield base_url
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)
        # Cleanup
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM plants WHERE id NOT IN ('plant_demo_membrane', 'plant_water_district_9');"
            )
            conn.commit()
        finally:
            conn.close()


def test_create_plant(ownership_server):
    """1. Any signed-in Clerk user can create a plant via POST /api/me/plants.
    Returns 201 with generated device credentials and one-time viewer token.
    Recorded in plant_members with role='owner'.
    """
    token = mint_user_jwt(sub="user_alice_123")
    payload = make_plant_payload("plant_alice_solar", "Alice Solar Plant")

    status, _, data = api_request(
        f"{ownership_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201, f"Expected 201, got {status}: {data}"
    assert data["plant_id"] == "plant_alice_solar"
    assert data["has_viewer_token"] is True
    assert data.get("one_time_viewer_token") or data.get("viewer_token")
    assert data.get("one_time_device_credentials")

    # Check plant_members in DB
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, plant_id, role FROM plant_members WHERE plant_id = 'plant_alice_solar';"
        )
        row = cur.fetchone()
        assert row is not None, "plant_members row not created"
        assert row["user_id"] == "user_alice_123"
        assert row["role"] == "owner"
    finally:
        conn.close()

    # GET /api/me/plants should list Alice's plant
    status, _, plants = api_request(
        f"{ownership_server}/api/me/plants",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    assert status == 200
    assert any(p["plant_id"] == "plant_alice_solar" for p in plants)


def test_user_plant_quota_4th_plant_returns_409(ownership_server):
    """2. Maximum 3 plants per user; the 4th attempt returns HTTP 409 Conflict."""
    token = mint_user_jwt(sub="user_quota_tester")

    for i in range(1, 4):
        payload = make_plant_payload(f"plant_quota_{i}", f"Quota Plant {i}")
        status, _, data = api_request(
            f"{ownership_server}/api/me/plants",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
        )
        assert status == 201, f"Plant {i} failed: {data}"

    # 4th plant must fail with 409
    payload_4 = make_plant_payload("plant_quota_4", "Quota Plant 4")
    status, _, data = api_request(
        f"{ownership_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload_4).encode("utf-8"),
    )
    assert status == 409, f"Expected 409 for 4th plant, got {status}: {data}"


def test_global_cap_returns_409(ownership_server):
    """3. Maximum 25 plants in total; beyond that returns HTTP 409 Conflict."""
    conn = get_db_connection()
    created_dummy_ids = []
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) as cnt FROM plants;")
        current_count = cur.fetchone()["cnt"]

        # Insert dummy plants to reach 25
        needed = 25 - current_count
        for i in range(needed):
            dummy_id = f"dummy_global_cap_{i}"
            created_dummy_ids.append(dummy_id)
            cur.execute(
                "INSERT INTO plants (id, name, timezone) VALUES (%s, %s, 'UTC');",
                (dummy_id, f"Dummy {i}"),
            )
        conn.commit()
    finally:
        conn.close()

    # Now total is 25. Attempting to create one more must fail with 409
    token = mint_user_jwt(sub="user_cap_verifier")
    payload = make_plant_payload("plant_cap_overflow", "Cap Overflow Plant")
    status, _, data = api_request(
        f"{ownership_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 409, f"Expected 409 for global cap, got {status}: {data}"

    # Cleanup dummy plants
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for did in created_dummy_ids:
            cur.execute("DELETE FROM plants WHERE id = %s;", (did,))
        conn.commit()
    finally:
        conn.close()


def test_unauthenticated_returns_401(ownership_server):
    """4. Unauthenticated requests to /api/me routes return 401."""
    # No header on POST
    status, _, _ = api_request(
        f"{ownership_server}/api/me/plants",
        method="POST",
        data=json.dumps(make_plant_payload("plant_unauth")).encode("utf-8"),
    )
    assert status == 401

    # No header on GET
    status, _, _ = api_request(f"{ownership_server}/api/me/plants", method="GET")
    assert status == 401

    # Invalid Bearer on GET
    status, _, _ = api_request(
        f"{ownership_server}/api/me/plants",
        headers={"Authorization": "Bearer invalid_jwt_token_123"},
        method="GET",
    )
    assert status == 401


def test_user_b_cannot_view_user_a_token_plant(ownership_server):
    """5. User B with a valid Clerk token cannot view User A's private plant without viewer token."""
    # User A creates plant
    token_a = mint_user_jwt(sub="user_alice_priv")
    payload = make_plant_payload("plant_alice_priv", "Alice Private")
    status, _, _data = api_request(
        f"{ownership_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token_a}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201

    # User B attempts to access machines/latest with User B token
    token_b = mint_user_jwt(sub="user_bob_intruder")
    status, _, data_b = api_request(
        f"{ownership_server}/api/plants/plant_alice_priv/machines/latest",
        headers={"Authorization": f"Bearer {token_b}"},
        method="GET",
    )
    assert status == 401, f"User B should be refused with 401, got {status}: {data_b}"

    # User B attempts to mint ws-ticket
    status_ws, _, _ = api_request(
        f"{ownership_server}/api/plants/plant_alice_priv/ws-ticket",
        headers={"Authorization": f"Bearer {token_b}"},
        method="POST",
    )
    assert status_ws == 401, (
        f"User B ws-ticket should be refused with 401, got {status_ws}"
    )


def test_owner_views_without_viewer_token(ownership_server):
    """6. Owner can view machines/latest, definition, and mint ws-ticket using Clerk token."""
    token_a = mint_user_jwt(sub="user_alice_owner")
    payload = make_plant_payload("plant_alice_owner", "Alice Owner Plant")
    status, _, _ = api_request(
        f"{ownership_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token_a}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201

    # Owner views machines/latest without viewer token
    status, _, machines = api_request(
        f"{ownership_server}/api/plants/plant_alice_owner/machines/latest",
        headers={"Authorization": f"Bearer {token_a}"},
        method="GET",
    )
    assert status == 200, f"Owner should view with 200, got {status}: {machines}"

    # Owner views plant definition
    status_def, _, _plant_def = api_request(
        f"{ownership_server}/api/plants/plant_alice_owner/definition",
        headers={"Authorization": f"Bearer {token_a}"},
        method="GET",
    )
    assert status_def == 200

    # Owner mints ws-ticket
    status_ws, _, ticket_data = api_request(
        f"{ownership_server}/api/plants/plant_alice_owner/ws-ticket",
        headers={"Authorization": f"Bearer {token_a}"},
        method="POST",
    )
    assert status_ws == 200
    assert "ticket" in ticket_data


def test_user_with_no_role_gets_403_on_admin(ownership_server):
    """7. User with valid Clerk token but no role claim receives 403 Forbidden on /api/admin/*."""
    token_no_role = mint_user_jwt(sub="user_no_role", role=None)

    status, _, data = api_request(
        f"{ownership_server}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_no_role}"},
        method="GET",
    )
    assert status == 403, f"Expected 403 for user with no role, got {status}: {data}"


def test_platform_admin_sees_all(ownership_server):
    """8. Platform admin with Clerk token can view any private plant without the viewer token."""
    # User A creates plant
    token_a = mint_user_jwt(sub="user_alice_super")
    payload = make_plant_payload("plant_alice_super", "Alice Super Plant")
    status, _, _ = api_request(
        f"{ownership_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token_a}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201

    # Platform admin views User A's plant
    token_admin = mint_user_jwt(sub="user_admin_global", role="platform_admin")
    status, _, data = api_request(
        f"{ownership_server}/api/plants/plant_alice_super/machines/latest",
        headers={"Authorization": f"Bearer {token_admin}"},
        method="GET",
    )
    assert status == 200, f"Platform admin should access with 200, got {status}: {data}"

    # Platform admin mints ws-ticket for User A's plant
    status_ws, _, ws_data = api_request(
        f"{ownership_server}/api/plants/plant_alice_super/ws-ticket",
        headers={"Authorization": f"Bearer {token_admin}"},
        method="POST",
    )
    assert status_ws == 200
    assert "ticket" in ws_data


def test_demo_plant_and_viewer_token_flow_unchanged(ownership_server):
    """9. Demo plant is anonymously viewable; protected water plant requires viewer token."""
    # Demo plant anonymously viewable
    status, _, _data = api_request(
        f"{ownership_server}/api/plants/plant_demo_membrane/machines/latest",
        method="GET",
    )
    assert status == 200, f"Demo plant should be public, got {status}"

    # Water plant without token fails with 401
    status_unauth, _, _ = api_request(
        f"{ownership_server}/api/plants/plant_water_district_9/machines/latest",
        method="GET",
    )
    assert status_unauth == 401

    # Water plant with valid viewer token succeeds with 200
    status_auth, _, _ = api_request(
        f"{ownership_server}/api/plants/plant_water_district_9/machines/latest",
        headers={"Authorization": "Bearer district9_read_secret_token_889"},
        method="GET",
    )
    assert status_auth == 200


def test_membership_rows_cascade_when_plant_deleted(ownership_server):
    """10. Membership rows in plant_members cascade-delete when a plant is deleted."""
    token_a = mint_user_jwt(sub="user_alice_del")
    payload = make_plant_payload("plant_alice_del", "Alice Deletion Plant")
    status, _, _ = api_request(
        f"{ownership_server}/api/me/plants",
        headers={
            "Authorization": f"Bearer {token_a}",
            "Content-Type": "application/json",
        },
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )
    assert status == 201

    # Verify membership row exists
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) as cnt FROM plant_members WHERE plant_id = 'plant_alice_del';"
        )
        assert cur.fetchone()["cnt"] == 1
    finally:
        conn.close()

    # Platform admin deletes the plant via admin API
    token_admin = mint_user_jwt(sub="user_admin_del", role="platform_admin")
    status_del, _, _ = api_request(
        f"{ownership_server}/api/admin/plants/plant_alice_del",
        headers={"Authorization": f"Bearer {token_admin}"},
        method="DELETE",
    )
    assert status_del == 200

    # Verify membership row was cascade deleted
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) as cnt FROM plant_members WHERE plant_id = 'plant_alice_del';"
        )
        assert cur.fetchone()["cnt"] == 0
    finally:
        conn.close()
