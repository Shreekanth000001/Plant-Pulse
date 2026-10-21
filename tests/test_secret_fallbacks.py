import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.generate_mosquitto_auth import (
    generate_auth_files,
    sync_broker_auth_from_db,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_mock_db(conn: sqlite3.Connection):
    conn.execute("CREATE TABLE plants (id TEXT PRIMARY KEY, name TEXT);")
    conn.execute(
        "CREATE TABLE plant_credentials (plant_id TEXT, username TEXT, password_hash TEXT, is_active INTEGER, PRIMARY KEY (plant_id, username));"
    )
    conn.execute("INSERT INTO plants VALUES ('plant_demo', 'Demo Plant');")
    conn.execute(
        "INSERT INTO plant_credentials VALUES ('plant_demo', 'user1', '$7$101$abcd$efgh', 1);"
    )
    conn.commit()


def test_sync_broker_auth_fails_closed_without_backend_password(tmp_path, monkeypatch):
    """sync_broker_auth_from_db must fail closed (raise ValueError) when backend_password is not provided or empty, and never fallback to 'backend_service_secret'."""
    monkeypatch.delenv("BACKEND_MQTT_PASSWORD", raising=False)
    monkeypatch.delenv("MQTT_PASSWORD", raising=False)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    make_mock_db(conn)

    auth_dir = tmp_path / "auth"
    with pytest.raises(ValueError) as excinfo:
        sync_broker_auth_from_db(
            conn=conn,
            auth_dir=auth_dir,
            backend_user="backend_service",
            backend_password=None,
            reload=False,
        )
    err = str(excinfo.value)
    assert "backend_service_secret" not in err
    assert not (auth_dir / "passwd").exists()


def test_generate_auth_files_fails_closed_without_backend_password(tmp_path):
    """generate_auth_files must raise ValueError when backend_password is None or empty."""
    auth_dir = tmp_path / "auth"
    passwd_path = auth_dir / "passwd"
    acl_path = auth_dir / "acl.conf"

    with pytest.raises(ValueError) as excinfo:
        generate_auth_files(
            plants_dir=REPO_ROOT / "plants",
            passwd_path=passwd_path,
            acl_path=acl_path,
            backend_user="backend_service",
            backend_password=None,
        )
    err = str(excinfo.value)
    assert "backend_service_secret" not in err


def test_cli_generate_auth_fails_closed_without_backend_password(tmp_path):
    """Invoking generate_mosquitto_auth.py without backend password must exit non-zero and not default to backend_service_secret."""
    env = os.environ.copy()
    env.pop("BACKEND_MQTT_PASSWORD", None)
    env.pop("BACKEND_SERVICE_PASSWORD", None)
    env["MQTT_PASSWORD"] = "demo_membrane_secure_token_123"
    env["WATER_MQTT_PASSWORD"] = "water_district_edge_key_771"

    res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate_mosquitto_auth.py"),
            "--plants-dir",
            str(REPO_ROOT / "plants"),
            "--passwd-path",
            str(tmp_path / "passwd"),
            "--acl-path",
            str(tmp_path / "acl.conf"),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode != 0, f"Expected non-zero exit code when password missing, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"
    assert "backend_service_secret" not in res.stdout
    assert "backend_service_secret" not in res.stderr


def test_docker_compose_has_no_demo_secret_fallbacks():
    """docker-compose.yml must not contain any hardcoded demo secrets in fallback expressions (${VAR:-demo_secret})."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    content = compose_path.read_text(encoding="utf-8")

    forbidden_secrets = [
        "demo_membrane_secure_token_123",
        "water_district_edge_key_771",
        "district9_read_secret_token_889",
        "backend_service_secret",
    ]
    for secret in forbidden_secrets:
        assert secret not in content, f"Found hardcoded fallback secret '{secret}' in docker-compose.yml"
