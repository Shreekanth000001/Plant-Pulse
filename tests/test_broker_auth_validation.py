import http.client
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import uvicorn
from pydantic import ValidationError

from main import build_app
from plant_definitions import (
    MQTTCredential,
    PlantDefinition,
)
from scripts.generate_mosquitto_auth import (
    generate_acl_content,
    sync_broker_auth_from_db,
)

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"


def make_valid_plant_dict(plant_id: str = "valid_plant_1") -> dict:
    return {
        "plant_id": plant_id,
        "name": "Valid Test Manufacturing Plant",
        "timezone": "UTC",
        "enabled_modules": ["core", "alarms"],
        "mqtt_credentials": [
            {
                "username": f"device_{plant_id}",
                "password": "secure_device_token_123",
                "client_id": f"client_{plant_id}",
            }
        ],
        "areas": [
            {
                "area_code": "area_main",
                "name": "Main Production Area",
                "display_order": 0,
                "machines": [
                    {
                        "machine_code": "mach_01",
                        "name": "Extruder Machine 1",
                        "machine_type": "extruder",
                        "display_order": 0,
                        "signals": [
                            {
                                "signal_code": "sig_temp",
                                "name": "Temperature",
                                "unit": "C",
                                "data_type": "float",
                                "display_order": 0,
                            }
                        ],
                    }
                ],
            }
        ],
    }


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


# ============================================================================
# 1. Plant name validation: reject \n, \r, and control characters
# ============================================================================


@pytest.mark.parametrize(
    "hostile_name",
    [
        "Plant\nuser evil\ntopic readwrite #",
        "Plant\ruser evil",
        "Plant\r\nuser evil",
        "Plant\x00NullByte",
        "Plant\x1b[31mEscape",
        "Plant\x07Bell",
    ],
)
def test_plant_name_with_newline_or_control_chars_rejected(hostile_name):
    """Criterion 1: Plant name with newline, carriage return, or control characters must be rejected (422)."""
    data = make_valid_plant_dict()
    data["name"] = hostile_name
    with pytest.raises(ValidationError) as exc:
        PlantDefinition.model_validate(data)
    assert "name" in str(exc.value)


# ============================================================================
# 2. MQTT Username validation: regex ^[a-z0-9_]{3,64}$
# ============================================================================


@pytest.mark.parametrize(
    "hostile_username",
    [
        "user\nnewline",
        "user\rreturn",
        "user:colon:admin",
        "user space",
        "user#hash",
        "user+plus",
        "user/slash",
        "UPPERCASE_USER",
        "ab",  # too short (< 3)
        "a" * 65,  # too long (> 64)
    ],
)
def test_mqtt_username_hostile_chars_rejected(hostile_username):
    """Criterion 2: MQTT username with newline, colon, space, wildcards, or invalid length must be rejected (422)."""
    data = make_valid_plant_dict()
    data["mqtt_credentials"] = [
        {
            "username": hostile_username,
            "password": "valid_password_123",
            "client_id": "valid_client_id",
        }
    ]
    with pytest.raises(ValidationError) as exc:
        PlantDefinition.model_validate(data)
    assert "username" in str(exc.value)


def test_existing_usernames_and_auto_generated_usernames_pass():
    """Criterion 2 & 1: Existing usernames and all generated device_{plant_id} must pass regex validation."""
    existing_users = [
        "device_plant_demo_membrane",
        "backend_service",
        "device_plant_water_district_9",
        "device_valid_plant_1",
    ]
    for u in existing_users:
        cred = MQTTCredential(
            username=u, password="test_password", client_id="test_client"
        )
        assert cred.username == u


# ============================================================================
# 3. Password validation: reject newlines and carriage returns
# ============================================================================


@pytest.mark.parametrize(
    "hostile_password",
    [
        "pass\nword",
        "pass\rword",
        "pass\r\nword",
    ],
)
def test_password_with_newline_rejected(hostile_password):
    """Criterion 3: Password with newline or carriage return must be rejected (422)."""
    data = make_valid_plant_dict()
    data["mqtt_credentials"][0]["password"] = hostile_password
    with pytest.raises(ValidationError) as exc:
        PlantDefinition.model_validate(data)
    assert "password" in str(exc.value)


# ============================================================================
# 4. plant_id bounds: max 57 characters so device_{plant_id} <= 64
# ============================================================================


def test_plant_id_length_57_passes_and_58_rejected():
    """Criterion 4: plant_id max length is 57 so device_{plant_id} (7 + 57 = 64) fits username limit."""
    id_57 = "p" * 57
    id_58 = "p" * 58

    # 57 chars must pass
    data_57 = make_valid_plant_dict(plant_id=id_57)
    plant_57 = PlantDefinition.model_validate(data_57)
    auto_user_57 = f"device_{plant_57.plant_id}"
    assert len(auto_user_57) == 64
    # Auto username must be valid against username regex
    MQTTCredential(username=auto_user_57, password="pwd", client_id="client")

    # 58 chars must fail
    data_58 = make_valid_plant_dict(plant_id=id_58)
    with pytest.raises(ValidationError) as exc:
        PlantDefinition.model_validate(data_58)
    assert "plant_id" in str(exc.value)


# ============================================================================
# 5. Topology count caps: max 100 machines, max 100 signals/machine, max 500 signals total
# ============================================================================


def test_machines_per_plant_cap_100_rejected_when_exceeded():
    """Criterion 5: More than 100 machines per plant must be rejected (422)."""
    data = make_valid_plant_dict()
    # Create 101 machines
    machines = []
    for i in range(101):
        machines.append(
            {
                "machine_code": f"m_{i:03d}",
                "name": f"Machine {i}",
                "machine_type": "standard",
                "display_order": i,
                "signals": [
                    {
                        "signal_code": "sig_1",
                        "name": "Sig 1",
                        "unit": "V",
                        "data_type": "float",
                        "display_order": 0,
                    }
                ],
            }
        )
    data["areas"][0]["machines"] = machines

    with pytest.raises(ValidationError) as exc:
        PlantDefinition.model_validate(data)
    assert "machines" in str(exc.value).lower()


def test_signals_per_machine_cap_100_rejected_when_exceeded():
    """Criterion 5: More than 100 signals on a single machine must be rejected (422)."""
    data = make_valid_plant_dict()
    signals = []
    for i in range(101):
        signals.append(
            {
                "signal_code": f"s_{i:03d}",
                "name": f"Signal {i}",
                "unit": "psi",
                "data_type": "float",
                "display_order": i,
            }
        )
    data["areas"][0]["machines"][0]["signals"] = signals

    with pytest.raises(ValidationError) as exc:
        PlantDefinition.model_validate(data)
    assert "signals" in str(exc.value).lower()


def test_signals_total_per_plant_cap_500_rejected_when_exceeded():
    """Criterion 5: Cap of 500 signals total across all machines in a plant (422)."""
    data = make_valid_plant_dict()
    # 6 machines with 85 signals each = 510 signals (> 500)
    machines = []
    for m in range(6):
        signals = [
            {
                "signal_code": f"s_{s:03d}",
                "name": f"Signal {s}",
                "unit": "C",
                "data_type": "float",
                "display_order": s,
            }
            for s in range(85)
        ]
        machines.append(
            {
                "machine_code": f"mach_{m:02d}",
                "name": f"Machine {m}",
                "machine_type": "standard",
                "display_order": m,
                "signals": signals,
            }
        )
    data["areas"][0]["machines"] = machines

    with pytest.raises(ValidationError) as exc:
        PlantDefinition.model_validate(data)
    assert "signals" in str(exc.value).lower()


# ============================================================================
# 6. Request Body Limit on Admin Plant Routes: > 1 MB returns 413
# ============================================================================


def test_admin_post_plant_body_over_1mb_returns_413(monkeypatch):
    """Criterion 6: Request body over 1 MB on admin plant routes returns 413 Payload Too Large."""
    monkeypatch.setenv("ADMIN_TOKEN", "test_admin_token_123")
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    app = build_app()
    srv, thread, base_url, _port = run_test_server(app)
    try:
        # 1.05 MB payload
        large_padding = "x" * (1024 * 1024 + 50 * 1024)
        data = make_valid_plant_dict()
        data["name"] = f"Valid Plant {large_padding}"
        body_bytes = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(
            f"{base_url}/api/admin/plants",
            data=body_bytes,
            headers={
                "Authorization": "Bearer test_admin_token_123",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5.0)
            pytest.fail("Expected 413 Payload Too Large")
        except urllib.error.HTTPError as exc:
            assert exc.code == 413
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


def test_admin_post_plant_chunked_body_over_1mb_returns_413(monkeypatch):
    """Criterion 6: Chunked transfer encoding without Content-Length exceeding 1MB returns 413."""
    monkeypatch.setenv("ADMIN_TOKEN", "test_admin_token_123")
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    app = build_app()
    srv, thread, _base_url, port = run_test_server(app)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        conn.putrequest("POST", "/api/admin/plants")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Authorization", "Bearer test_admin_token_123")
        conn.endheaders()

        # Send initial chunk
        prefix = b'{"plant_id": "test_chunk", "name": "'
        conn.send(f"{len(prefix):X}\r\n".encode("ascii") + prefix + b"\r\n")

        # Stream chunks totaling 1.1 MB
        chunk_data = b"A" * 65536
        chunk_header = f"{len(chunk_data):X}\r\n".encode("ascii")
        try:
            for _ in range(18):  # 18 * 64KB = 1.15 MB
                conn.send(chunk_header + chunk_data + b"\r\n")

            suffix = b'"}'
            conn.send(f"{len(suffix):X}\r\n".encode("ascii") + suffix + b"\r\n")
            conn.send(b"0\r\n\r\n")
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

        resp = conn.getresponse()
        assert resp.status == 413
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


# ============================================================================
# 7. ACL & Passwd Generation: No injected lines, plant_id used in comment header
# ============================================================================


def test_generate_acl_content_stops_interpolating_plant_name():
    """Criterion 7: generate_acl_content stops interpolating plant.name; uses plant_id strictly."""
    data = make_valid_plant_dict("safe_plant_id")
    data["name"] = "Arbitrary Unescaped Human Name"
    plant = PlantDefinition.model_validate(data)
    plants = {plant.plant_id: plant}

    acl = generate_acl_content(plants, backend_user="backend_service")
    # Must use plant_id in comment header
    assert "# Plant: safe_plant_id" in acl
    # Must NOT interpolate human plant name into comment header
    assert "Arbitrary Unescaped Human Name" not in acl


# ============================================================================
# 8. Defense-in-depth: sync_broker_auth_from_db skips invalid rows, app stays up
# ============================================================================


def test_sync_broker_auth_from_db_skips_invalid_rows_and_fails_closed(tmp_path, caplog):
    """Criterion 8: sync_broker_auth_from_db skips and logs invalid DB rows, writes nothing for them, and succeeds."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    # Credentials: 1 valid, 2 invalid rows (newline injection and colon injection)
    mock_cursor.fetchall.side_effect = [
        # cred_rows
        [
            {
                "plant_id": "valid_plant",
                "username": "device_valid_plant",
                "password_hash": "$7$mockhash",
            },
            {
                "plant_id": "valid_plant",
                "username": "evil\nuser evil",
                "password_hash": "$7$badhash",
            },
            {
                "plant_id": "valid_plant",
                "username": "bad:colon:user",
                "password_hash": "$7$badhash2",
            },
            {
                "plant_id": "invalid_plant_id_because_it_has_newlines\n",
                "username": "device_invalid_pid",
                "password_hash": "$7$badhash3",
            },
        ],
        # plant_rows
        [
            {"id": "valid_plant", "name": "Valid Plant"},
            {
                "id": "invalid_plant_id_because_it_has_newlines\n",
                "name": "Hostile Plant",
            },
        ],
    ]

    auth_dir = tmp_path / "mosquitto_auth"
    auth_dir.mkdir()

    with caplog.at_level(logging.WARNING):
        success = sync_broker_auth_from_db(
            conn=mock_conn,
            auth_dir=auth_dir,
            backend_user="backend_service",
            backend_password="backend_password_123",
            reload=False,
        )

    assert success is True

    passwd_content = (auth_dir / "passwd").read_text(encoding="utf-8")
    acl_content = (auth_dir / "acl.conf").read_text(encoding="utf-8")

    # Valid user written
    assert "backend_service:" in passwd_content
    assert "device_valid_plant:" in passwd_content
    assert "user device_valid_plant" in acl_content

    # Hostile users MUST NOT be in passwd or acl.conf
    assert "evil\nuser evil" not in passwd_content
    assert "bad:colon:user" not in passwd_content
    assert "user evil\n" not in acl_content
    assert "invalid_plant_id" not in acl_content

    # Logged warnings for skipped invalid records
    assert any(
        "skipping invalid" in r.message.lower()
        or "invalid username" in r.message.lower()
        for r in caplog.records
    )


def test_existing_valid_plants_produce_identical_passwd_and_acl(tmp_path):
    """Criterion 8: Existing valid plants produce valid files with all expected entries."""
    from scripts.generate_mosquitto_auth import generate_auth_files

    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    passwd_file = auth_dir / "passwd"
    acl_file = auth_dir / "acl.conf"

    generate_auth_files(
        plants_dir=PLANTS_DIR,
        passwd_path=passwd_file,
        acl_path=acl_file,
        backend_user="backend_service",
        backend_password="backend_password_123",
    )

    passwd_text = passwd_file.read_text(encoding="utf-8")
    acl_text = acl_file.read_text(encoding="utf-8")

    assert "backend_service:" in passwd_text
    assert "device_plant_demo_membrane:" in passwd_text
    assert "device_plant_water_district_9:" in passwd_text

    assert "user backend_service" in acl_text
    assert "user device_plant_demo_membrane" in acl_text
    assert "topic readwrite plants/plant_demo_membrane/#" in acl_text
    assert "user device_plant_water_district_9" in acl_text
    assert "topic readwrite plants/plant_water_district_9/#" in acl_text


def test_admin_post_plant_first_chunk_over_1mb_never_runs_handler_or_validation(
    monkeypatch,
):
    """Body limit: first chunk alone exceeds 1 MB with no Content-Length returns 413 without running handler/validation."""
    monkeypatch.setenv("ADMIN_TOKEN", "test_admin_token_123")
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    app = build_app()
    srv, thread, _base_url, port = run_test_server(app)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        conn.putrequest("POST", "/api/admin/plants")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Authorization", "Bearer test_admin_token_123")
        conn.endheaders()

        # A single first chunk of 1.2 MB containing non-JSON garbage
        # If handler or JSON validation ran, it would fail with 422 JSONDecodeError instead of 413
        single_big_chunk = b"X" * (1200 * 1024)
        conn.send(
            f"{len(single_big_chunk):X}\r\n".encode("ascii")
            + single_big_chunk
            + b"\r\n"
        )
        conn.send(b"0\r\n\r\n")

        resp = conn.getresponse()
        assert resp.status == 413
        body = resp.read()
        assert b"Payload Too Large" in body
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)


@pytest.mark.parametrize(
    "bad_backend_user",
    [
        "backend\nuser",
        "backend:user",
        "BACKEND_USER",
    ],
)
def test_backend_user_malformed_raises_value_error(bad_backend_user, tmp_path):
    """Backend user must match ^[a-z0-9_]{3,64}$; malformed raises ValueError across all auth gen functions."""
    from scripts.generate_mosquitto_auth import (
        generate_acl_content,
        generate_auth_files,
        sync_broker_auth_from_db,
    )

    plants = {"p01": PlantDefinition.model_validate(make_valid_plant_dict("p01"))}
    with pytest.raises(ValueError, match="backend.*username"):
        generate_acl_content(plants, backend_user=bad_backend_user)

    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    with pytest.raises(ValueError, match="backend.*username"):
        generate_auth_files(
            plants_dir=PLANTS_DIR,
            passwd_path=auth_dir / "passwd",
            acl_path=auth_dir / "acl.conf",
            backend_user=bad_backend_user,
            backend_password="valid_password_123",
        )

    mock_conn = MagicMock()
    with pytest.raises(ValueError, match="backend.*username"):
        sync_broker_auth_from_db(
            conn=mock_conn,
            auth_dir=auth_dir,
            backend_user=bad_backend_user,
            backend_password="valid_password_123",
            reload=False,
        )


@pytest.mark.parametrize(
    "bad_backend_password",
    [
        "secret\npass",
        "secret\x00pass",
    ],
)
def test_backend_password_malformed_raises_value_error(bad_backend_password, tmp_path):
    """Backend password with newline or control chars raises ValueError in generate_auth_files and sync_broker_auth_from_db."""
    from scripts.generate_mosquitto_auth import (
        generate_auth_files,
        sync_broker_auth_from_db,
    )

    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    with pytest.raises(ValueError, match="Backend MQTT password"):
        generate_auth_files(
            plants_dir=PLANTS_DIR,
            passwd_path=auth_dir / "passwd",
            acl_path=auth_dir / "acl.conf",
            backend_user="backend_service",
            backend_password=bad_backend_password,
        )

    mock_conn = MagicMock()
    with pytest.raises(ValueError, match="Backend MQTT password"):
        sync_broker_auth_from_db(
            conn=mock_conn,
            auth_dir=auth_dir,
            backend_user="backend_service",
            backend_password=bad_backend_password,
            reload=False,
        )


def test_plant_name_length_bounds():
    """PlantDefinition.name length 1-128: 0 rejected, 128 passes, 129 rejected."""
    # 0 length (empty string) rejected
    data_0 = make_valid_plant_dict()
    data_0["name"] = ""
    with pytest.raises(ValidationError):
        PlantDefinition.model_validate(data_0)

    # 128 characters passes
    data_128 = make_valid_plant_dict()
    data_128["name"] = "P" * 128
    plant_128 = PlantDefinition.model_validate(data_128)
    assert len(plant_128.name) == 128

    # 129 characters rejected
    data_129 = make_valid_plant_dict()
    data_129["name"] = "P" * 129
    with pytest.raises(ValidationError):
        PlantDefinition.model_validate(data_129)


def test_app_starts_when_db_holds_invalid_plants(caplog):
    """App starts when DB holds plants with 101 machines, 58-char plant_id, and control char in name; bad plants skipped and logged."""
    from db import get_db_connection
    from plant_definitions import load_plants_from_db

    conn = get_db_connection()
    pid_58 = "p" * 58
    try:
        cur = conn.cursor()
        # Clean test table entries if present
        cur.execute(
            "DELETE FROM plants WHERE id IN (%s, 'plant_bad_ctrl', 'plant_101_mach');",
            (pid_58,),
        )
        conn.commit()

        # Plant 1: 58-char plant_id
        assert len(pid_58) == 58
        cur.execute(
            "INSERT INTO plants (id, name, timezone) VALUES (%s, %s, %s);",
            (pid_58, "Plant 58", "UTC"),
        )

        # Plant 2: Control character in name (ASCII 27 ESC)
        cur.execute(
            "INSERT INTO plants (id, name, timezone) VALUES (%s, %s, %s);",
            ("plant_bad_ctrl", "Plant\x1bBad", "UTC"),
        )

        # Plant 3: 101 machines
        cur.execute(
            "INSERT INTO plants (id, name, timezone) VALUES (%s, %s, %s);",
            ("plant_101_mach", "Plant 101 Machines", "UTC"),
        )
        cur.execute(
            "INSERT INTO areas (plant_id, area_code, name, display_order) VALUES (%s, %s, %s, %s);",
            ("plant_101_mach", "area_main", "Main Area", 0),
        )
        for m in range(101):
            cur.execute(
                "INSERT INTO machines (plant_id, area_code, machine_code, name, machine_type, display_order) VALUES (%s, %s, %s, %s, %s, %s);",
                (
                    "plant_101_mach",
                    "area_main",
                    f"m_{m:03d}",
                    f"Machine {m}",
                    "standard",
                    m,
                ),
            )
        conn.commit()

        with caplog.at_level(logging.WARNING):
            loaded = load_plants_from_db(conn)

        # Confirm all 3 bad plants were skipped
        assert pid_58 not in loaded
        assert "plant_bad_ctrl" not in loaded
        assert "plant_101_mach" not in loaded

        # Confirm valid plants (demo plants) are still loaded and working
        assert "plant_demo_membrane" in loaded
        assert "plant_water_district_9" in loaded

        # Confirm warnings were logged
        warning_msgs = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert any(pid_58 in m for m in warning_msgs)
        assert any("plant_bad_ctrl" in m for m in warning_msgs)
        assert any("plant_101_mach" in m for m in warning_msgs)
    finally:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM plants WHERE id IN (%s, 'plant_bad_ctrl', 'plant_101_mach');",
            (pid_58,),
        )
        conn.commit()
        conn.close()
