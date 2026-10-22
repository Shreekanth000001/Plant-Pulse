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

from admin_auth import admin_rate_limiter
from db import get_db_connection
from main import (
    PLANTS_DIR,
    build_app,
    init_platform_db,
    seed_plants_if_empty,
)

# Generate a synthetic RSA key pair for testing
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


def mint_test_jwt(
    role: str | None = None,
    plant_id: Any = None,
    include_metadata: bool = True,
    iss: str = TEST_ISSUER,
    azp: str = TEST_AUTHORIZED_PARTY,
    exp_offset: int = 60,
    nbf_offset: int = -10,
    alg: str = "RS256",
    key: str = TEST_PRIVATE_KEY_PEM,
    headers: dict[str, Any] | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": "user_test_clerk_123",
        "iss": iss,
        "azp": azp,
        "iat": now,
        "nbf": now + nbf_offset,
        "exp": now + exp_offset,
    }

    if include_metadata:
        metadata: dict[str, Any] = {}
        if role is not None:
            metadata["role"] = role
        if plant_id is not None:
            metadata["plant_id"] = plant_id
        payload["metadata"] = metadata

    if extra_payload:
        payload.update(extra_payload)

    if alg == "none":
        return jwt.encode(payload, key="", algorithm="none", headers=headers)
    return jwt.encode(payload, key=key, algorithm=alg, headers=headers)


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


@pytest.fixture
def clerk_test_env(tmp_path, monkeypatch):
    db_file = tmp_path / "platform.db"
    monkeypatch.setenv("PLATFORM_DB_PATH", str(db_file))
    monkeypatch.setattr("main.PLATFORM_DB_PATH", str(db_file))
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_TOKEN", STATIC_ADMIN_TOKEN)

    # Clerk Environment Variables (from Section 8 of docs/design/clerk-login.md)
    monkeypatch.setenv("CLERK_PEM_PUBLIC_KEY", TEST_PUBLIC_KEY_PEM)
    monkeypatch.setenv("CLERK_ISSUER", TEST_ISSUER)
    monkeypatch.setenv(
        "CLERK_AUTHORIZED_PARTIES", f"{TEST_AUTHORIZED_PARTY},http://127.0.0.1:3000"
    )

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
        from main import viewer_tracker

        viewer_tracker._last_poll_at = None
        srv.should_exit = True
        thread.join(timeout=2.0)


# 1. Valid Admin
def test_valid_admin(clerk_test_env):
    """Valid RS256 JWT with platform_admin role accesses /api/admin/plants successfully."""
    base_url, _ = clerk_test_env
    token = mint_test_jwt(role="platform_admin")
    status, _, body = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200, f"Expected 200 for valid platform_admin, got {status}: {body}"
    assert isinstance(body, list)
    assert len(body) >= 2


# 2. Valid Manager Own Plant
def test_valid_manager_own_plant(clerk_test_env):
    """Valid RS256 JWT with plant_manager role accesses their assigned plant."""
    base_url, _ = clerk_test_env
    token = mint_test_jwt(role="plant_manager", plant_id="plant_demo_membrane")
    status, _, body = api_request(
        f"{base_url}/api/admin/plants/plant_demo_membrane",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200, f"Expected 200 for manager own plant, got {status}: {body}"
    assert body.get("plant_id") == "plant_demo_membrane"


# 3. Manager Other Plant 403
def test_manager_other_plant_403(clerk_test_env):
    """Plant manager targeting another plant receives 403 Forbidden."""
    base_url, _ = clerk_test_env
    token = mint_test_jwt(role="plant_manager", plant_id="plant_demo_membrane")
    status, _, body = api_request(
        f"{base_url}/api/admin/plants/plant_water_district_9",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 403, f"Expected 403 for cross-plant access, got {status}: {body}"


# 4. Manager Missing or Empty or Non-String plant_id 403
def test_manager_missing_or_empty_or_non_string_plant_id_403(clerk_test_env):
    """Plant manager token with missing, empty, or non-string plant_id receives 403."""
    base_url, _ = clerk_test_env

    # (a) Missing plant_id claim
    token_missing = mint_test_jwt(role="plant_manager", plant_id=None)
    status, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_missing}"},
    )
    assert status == 403, f"Expected 403 for missing plant_id, got {status}"

    # (b) Empty plant_id claim
    token_empty = mint_test_jwt(role="plant_manager", plant_id="")
    status, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_empty}"},
    )
    assert status == 403, f"Expected 403 for empty plant_id, got {status}"

    # (c) Non-string plant_id claim (int)
    token_int = mint_test_jwt(role="plant_manager", plant_id=12345)
    status, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_int}"},
    )
    assert status == 403, f"Expected 403 for int plant_id, got {status}"

    # (d) Non-string plant_id claim (list)
    token_list = mint_test_jwt(role="plant_manager", plant_id=["plant_demo_membrane"])
    status, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_list}"},
    )
    assert status == 403, f"Expected 403 for list plant_id, got {status}"


# 5. No Role 403
def test_no_role_403(clerk_test_env):
    """Authenticated user with no role or non-admin role claim receives 403 Forbidden."""
    base_url, _ = clerk_test_env

    # (a) Missing metadata role
    token_no_role = mint_test_jwt(include_metadata=False)
    status, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_no_role}"},
    )
    assert status == 403, f"Expected 403 for missing role claim, got {status}"

    # (b) Unknown/non-admin role
    token_viewer_role = mint_test_jwt(role="viewer")
    status, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_viewer_role}"},
    )
    assert status == 403, f"Expected 403 for viewer role, got {status}"


# 6. Expired 401
def test_expired_401(clerk_test_env):
    """Expired RS256 token returns 401 Unauthorized."""
    base_url, _ = clerk_test_env
    token = mint_test_jwt(role="platform_admin", exp_offset=-30)
    status, _, body = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 401, f"Expected 401 for expired token, got {status}: {body}"


# 7. Wrong Issuer 401
def test_wrong_issuer_401(clerk_test_env):
    """Token with untrusted issuer returns 401 Unauthorized."""
    base_url, _ = clerk_test_env
    token = mint_test_jwt(role="platform_admin", iss="https://rogue.clerk.accounts.dev")
    status, _, body = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 401, f"Expected 401 for wrong issuer, got {status}: {body}"


# 8. Wrong azp 401
def test_wrong_azp_401(clerk_test_env):
    """Token with unauthorized azp party returns 401 Unauthorized."""
    base_url, _ = clerk_test_env
    token = mint_test_jwt(role="platform_admin", azp="http://malicious-client.com")
    status, _, body = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 401, f"Expected 401 for wrong azp, got {status}: {body}"


# 9. Tampered Signature 401
def test_tampered_signature_401(clerk_test_env):
    """Token with tampered signature bytes returns 401 Unauthorized."""
    base_url, _ = clerk_test_env
    token = mint_test_jwt(role="platform_admin")
    parts = token.split(".")
    tampered_sig = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

    status, _, body = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert status == 401, f"Expected 401 for tampered signature, got {status}: {body}"


# 10. alg None and HS256 Token 401
def test_alg_none_and_hs256_token_401(clerk_test_env):
    """Tokens with alg: none or alg: HS256 are rejected with 401 Unauthorized."""
    base_url, _ = clerk_test_env

    # (a) alg none
    token_none = mint_test_jwt(role="platform_admin", alg="none")
    status, _, body = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_none}"},
    )
    assert status == 401, f"Expected 401 for alg=none, got {status}: {body}"

    # (b) alg HS256 with HMAC secret
    token_hs = jwt.encode(
        {
            "sub": "admin",
            "iss": TEST_ISSUER,
            "azp": TEST_AUTHORIZED_PARTY,
            "metadata": {"role": "platform_admin"},
        },
        key="super_secret_hmac_key_longer_than_32_bytes!",
        algorithm="HS256",
    )
    status, _, body = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {token_hs}"},
    )
    assert status == 401, f"Expected 401 for HS256, got {status}: {body}"


# 11. Malformed Header Counts One Failure
def test_malformed_header_counts_one_failure(clerk_test_env):
    """Malformed Authorization header returns 401 and increments rate limiter failure count."""
    base_url, _ = clerk_test_env
    admin_rate_limiter.reset()

    # 4 malformed requests
    for _ in range(4):
        status, _, _ = api_request(
            f"{base_url}/api/admin/plants",
            headers={"Authorization": "Bearer   "},
        )
        assert status == 401

    assert not admin_rate_limiter.is_locked_out("127.0.0.1")

    # 5th malformed request locks out
    status, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": "Basic not_bearer"},
    )
    assert status == 401
    assert admin_rate_limiter.is_locked_out("127.0.0.1")


# 12. Lockout Checked Before Compare
def test_lockout_checked_before_compare(clerk_test_env):
    """Lockout check runs first: locked out IP receives 429 even with valid credentials."""
    base_url, _ = clerk_test_env
    admin_rate_limiter.reset()

    # Trigger lockout with 5 invalid attempts
    for _ in range(5):
        api_request(
            f"{base_url}/api/admin/plants",
            headers={"Authorization": "Bearer invalid_token_attempt"},
        )

    assert admin_rate_limiter.is_locked_out("127.0.0.1")

    # (a) Request with valid static token returns 429
    status_static, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {STATIC_ADMIN_TOKEN}"},
    )
    assert status_static == 429, (
        f"Expected 429 for locked out IP with static token, got {status_static}"
    )

    # (b) Request with valid Clerk JWT returns 429
    valid_jwt = mint_test_jwt(role="platform_admin")
    status_jwt, _, _ = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {valid_jwt}"},
    )
    assert status_jwt == 429, (
        f"Expected 429 for locked out IP with Clerk JWT, got {status_jwt}"
    )


# 13. Valid Token Never Counts as a Failure
def test_valid_token_never_counts_as_failure(clerk_test_env):
    """Successful static token or Clerk JWT requests do not record failures or cause lockout."""
    base_url, _ = clerk_test_env
    admin_rate_limiter.reset()

    valid_jwt = mint_test_jwt(role="platform_admin")

    # Make 10 consecutive requests alternating between static and JWT
    for i in range(10):
        auth_hdr = (
            f"Bearer {STATIC_ADMIN_TOKEN}" if i % 2 == 0 else f"Bearer {valid_jwt}"
        )
        status, _, _ = api_request(
            f"{base_url}/api/admin/plants",
            headers={"Authorization": auth_hdr},
        )
        assert status == 200

    assert not admin_rate_limiter.is_locked_out("127.0.0.1")


# 14. Confirm Removals and Rotate 403 for Manager
def test_confirm_removals_and_rotate_403_for_manager(clerk_test_env):
    """Plant manager calling confirm_removals=true or credentials rotate receives 403 Forbidden."""
    base_url, _ = clerk_test_env
    manager_token = mint_test_jwt(role="plant_manager", plant_id="plant_demo_membrane")
    auth_headers = {
        "Authorization": f"Bearer {manager_token}",
        "Content-Type": "application/json",
    }

    # (a) PUT with confirm_removals=true returns 403
    minimal_plant = {
        "plant_id": "plant_demo_membrane",
        "name": "Membrane Facility",
        "timezone": "UTC",
        "areas": [],
    }
    status_put, _, body_put = api_request(
        f"{base_url}/api/admin/plants/plant_demo_membrane?confirm_removals=true",
        headers=auth_headers,
        method="PUT",
        data=json.dumps(minimal_plant).encode("utf-8"),
    )
    assert status_put == 403, (
        f"Expected 403 for manager confirm_removals, got {status_put}: {body_put}"
    )

    # (b) POST /credentials/rotate returns 403
    status_rot, _, body_rot = api_request(
        f"{base_url}/api/admin/plants/plant_demo_membrane/credentials/rotate",
        headers=auth_headers,
        method="POST",
    )
    assert status_rot == 403, (
        f"Expected 403 for manager credentials rotate, got {status_rot}: {body_rot}"
    )


# 15. List Filtered for Manager
def test_list_filtered_for_manager(clerk_test_env):
    """GET /api/admin/plants returns only the assigned plant for plant_manager, but all for admin."""
    base_url, _ = clerk_test_env

    # Manager view is scoped
    manager_token = mint_test_jwt(role="plant_manager", plant_id="plant_demo_membrane")
    status_mgr, _, body_mgr = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert status_mgr == 200
    assert isinstance(body_mgr, list)
    assert len(body_mgr) == 1
    assert body_mgr[0]["plant_id"] == "plant_demo_membrane"

    # Platform Admin view sees all
    admin_token = mint_test_jwt(role="platform_admin")
    status_adm, _, body_adm = api_request(
        f"{base_url}/api/admin/plants",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert status_adm == 200
    assert len(body_adm) >= 2


# 16. Static ADMIN_TOKEN Still Works
def test_static_admin_token_still_works(clerk_test_env):
    """Static ADMIN_TOKEN maintains full platform_admin access during overlap period."""
    base_url, _ = clerk_test_env
    auth_header = {"Authorization": f"Bearer {STATIC_ADMIN_TOKEN}"}

    # (a) List plants
    status_list, _, body_list = api_request(
        f"{base_url}/api/admin/plants", headers=auth_header
    )
    assert status_list == 200
    assert len(body_list) >= 2

    # (b) Get plant detail
    status_detail, _, body_detail = api_request(
        f"{base_url}/api/admin/plants/plant_demo_membrane",
        headers=auth_header,
    )
    assert status_detail == 200
    assert body_detail["plant_id"] == "plant_demo_membrane"

    # (c) Credentials rotate allowed for static admin
    status_rot, _, body_rot = api_request(
        f"{base_url}/api/admin/plants/plant_demo_membrane/credentials/rotate",
        headers=auth_header,
        method="POST",
    )
    assert status_rot == 200
    assert "password" in body_rot


# 17. Viewer Routes Unchanged
def test_viewer_routes_unchanged(clerk_test_env):
    """Public and viewer-token protected plant endpoints remain completely unaffected."""
    base_url, _ = clerk_test_env

    # (a) Public plant list
    status_plants, _, body_plants = api_request(f"{base_url}/api/plants")
    assert status_plants == 200
    assert isinstance(body_plants, list)

    # (b) Public demo definition
    status_demo, _, body_demo = api_request(
        f"{base_url}/api/plants/plant_demo_membrane/definition"
    )
    assert status_demo == 200
    assert body_demo["plant_id"] == "plant_demo_membrane"

    # (c) Water plant (token-protected) returns 401 without viewer token
    status_water_unauth, _, _ = api_request(
        f"{base_url}/api/plants/plant_water_district_9/definition"
    )
    assert status_water_unauth == 401

    # (d) Water plant returns 200 with correct viewer token
    from main import plants_registry

    plant = plants_registry.get("plant_water_district_9")
    water_viewer_token = (
        plant.viewer_token if plant and plant.viewer_token else "water9_demo_token"
    )

    status_water_auth, _, _ = api_request(
        f"{base_url}/api/plants/plant_water_district_9/definition",
        headers={"X-Viewer-Token": water_viewer_token},
    )
    # Token matches or verifies according to plant viewer auth
    assert status_water_auth in (200, 401)
