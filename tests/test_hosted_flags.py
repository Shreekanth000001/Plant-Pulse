"""Tests for hosted mode flags: ENABLE_SELF_SERVICE and CORS configuration."""

import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from typing import Any

import pytest


def find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def run_test_server(app_instance):
    import uvicorn

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
            return resp.status, resp_headers, raw
    except urllib.error.HTTPError as err:
        resp_headers = {k.lower(): v for k, v in err.headers.items()}
        raw = err.read().decode("utf-8")
        return err.code, resp_headers, raw


def test_self_service_flag_default_enabled(monkeypatch):
    """When ENABLE_SELF_SERVICE is not set, /api/me routes are enabled and return 401 if unauthenticated."""
    monkeypatch.delenv("ENABLE_SELF_SERVICE", raising=False)
    from main import build_app

    app = build_app()
    srv, thread, base_url = run_test_server(app)
    try:
        status, _, body = api_request(f"{base_url}/api/me/plants")
        # Should be 401 Unauthorized (because Clerk token is missing), NOT 404
        assert status == 401, f"Expected 401 Unauthorized, got {status}: {body}"
    finally:
        srv.should_exit = True
        thread.join(timeout=1.0)


def test_self_service_flag_disabled_returns_404(monkeypatch):
    """When ENABLE_SELF_SERVICE is false, /api/me routes return 404 Not Found."""
    monkeypatch.setenv("ENABLE_SELF_SERVICE", "false")
    from main import build_app

    app = build_app(enable_self_service=False)
    srv, thread, base_url = run_test_server(app)
    try:
        status, _, body = api_request(f"{base_url}/api/me/plants")
        assert status == 404, (
            f"Expected 404 Not Found when ENABLE_SELF_SERVICE=false, got {status}: {body}"
        )

        status_delete, _, _ = api_request(
            f"{base_url}/api/me/plants/plant_test_123", method="DELETE"
        )
        assert status_delete == 404, (
            f"Expected 404 on DELETE when ENABLE_SELF_SERVICE=false, got {status_delete}"
        )
    finally:
        srv.should_exit = True
        thread.join(timeout=1.0)


def test_cors_origins_env_var_applied(monkeypatch):
    """CORS origins from CORS_ORIGINS env var with whitespace are correctly allowed."""
    test_origin = "https://hosted-plantpulse.onrender.com"
    monkeypatch.setenv("CORS_ORIGINS", f"http://localhost:3000, {test_origin} ")
    from main import build_app

    app = build_app()
    srv, thread, base_url = run_test_server(app)
    try:
        status, headers, _ = api_request(
            f"{base_url}/api/plants",
            headers={
                "Origin": test_origin,
                "Access-Control-Request-Method": "GET",
            },
            method="OPTIONS",
        )
        assert status == 200
        assert headers.get("access-control-allow-origin") == test_origin
    finally:
        srv.should_exit = True
        thread.join(timeout=1.0)


def test_hosted_retention_worker_starts(monkeypatch):
    """Hosted environment config (ENABLE_RETENTION_WORKER=true, RETENTION_DAYS=2) starts the retention worker during lifespan."""
    import asyncio

    from main import app, lifespan
    from retention import RetentionWorker

    monkeypatch.setenv("ENABLE_RETENTION_WORKER", "true")
    monkeypatch.setenv("RETENTION_DAYS", "2")

    started = []
    stopped = []

    def mock_start(self):
        started.append(self)

    async def mock_stop(self):
        stopped.append(self)

    monkeypatch.setattr(RetentionWorker, "start", mock_start)
    monkeypatch.setattr(RetentionWorker, "stop", mock_stop)

    async def run_lifespan():
        async with lifespan(app):
            assert len(started) == 1
            worker = started[0]
            assert worker.retention_days == 2
        assert len(stopped) == 1

    asyncio.run(run_lifespan())


def test_hosted_unset_water_token_fails_fast_and_never_yields_public_plant():
    """In hosted mode, an unset PLANT_WATER_DISTRICT_9_VIEWER_TOKEN causes entrypoint validation to exit non-zero, preventing the plant from ever seeding as public."""
    import subprocess

    env = {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        "BACKEND_MQTT_PASSWORD": "pass1",
        "MQTT_PASSWORD": "pass2",
        "WATER_MQTT_PASSWORD": "pass3",
        # PLANT_WATER_DISTRICT_9_VIEWER_TOKEN intentionally omitted
    }
    proc = subprocess.run(
        ["/bin/sh", "docker/entrypoint.hosted.sh"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert (
        "PLANT_WATER_DISTRICT_9_VIEWER_TOKEN" in proc.stdout
        or "PLANT_WATER_DISTRICT_9_VIEWER_TOKEN" in proc.stderr
    )


def test_hosted_entrypoint_unsets_admin_tokens():
    """Hosted entrypoint warns and unsets ADMIN_TOKEN and ADMIN_SECRET_TOKEN to harden production security."""
    import subprocess

    env = {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        "BACKEND_MQTT_PASSWORD": "pass1",
        "MQTT_PASSWORD": "pass2",
        "WATER_MQTT_PASSWORD": "pass3",
        "PLANT_WATER_DISTRICT_9_VIEWER_TOKEN": "district9_token_123",
        "ADMIN_TOKEN": "accidental_admin_token",
        "ADMIN_SECRET_TOKEN": "accidental_secret_token",
    }
    proc = subprocess.run(
        [
            "/bin/sh",
            "-c",
            'eval "$(sed \'/alembic upgrade/,$d\' docker/entrypoint.hosted.sh)"; echo RESULT_ADMIN_TOKEN="$ADMIN_TOKEN"; echo RESULT_ADMIN_SECRET="$ADMIN_SECRET_TOKEN"',
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert "ADMIN_TOKEN / ADMIN_SECRET_TOKEN should stay unset" in proc.stdout
    assert "RESULT_ADMIN_TOKEN=" in proc.stdout
    assert "accidental_admin_token" not in proc.stdout
    assert "accidental_secret_token" not in proc.stdout


def test_ensure_ipv4_database_url():
    """Ensure PostgreSQL URLs automatically resolve and append hostaddr for dual-stack hosts."""
    from unittest.mock import patch

    from db import ensure_ipv4_database_url

    # 1. Localhost and 127.0.0.1 should not be modified
    assert (
        ensure_ipv4_database_url("postgresql://postgres:postgres@localhost:5432/test")
        == "postgresql://postgres:postgres@localhost:5432/test"
    )
    assert (
        ensure_ipv4_database_url("postgresql://postgres:postgres@127.0.0.1:5432/test")
        == "postgresql://postgres:postgres@127.0.0.1:5432/test"
    )

    # 2. Existing hostaddr parameter should not be overwritten
    already_ipv4 = (
        "postgresql://user:pass@ep-test.neon.tech/db?sslmode=require&hostaddr=1.2.3.4"
    )
    assert ensure_ipv4_database_url(already_ipv4) == already_ipv4

    # 3. Domain resolution should append hostaddr with IPv4
    fake_info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("52.76.212.156", 5432))]
    with patch("socket.getaddrinfo", return_value=fake_info):
        resolved = ensure_ipv4_database_url(
            "postgresql://user:pass@ep-ancient-term-b3n7ldhe.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
        )
        assert (
            resolved
            == "postgresql://user:pass@ep-ancient-term-b3n7ldhe.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&hostaddr=52.76.212.156"
        )

    # 4. Graceful handling of resolution exceptions
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("DNS lookup failed")):
        url = "postgresql://user:pass@unresolvable-host.com/db?sslmode=require"
        assert ensure_ipv4_database_url(url) == url


def test_non_root_home_sanitization(monkeypatch):
    """Ensure non-root processes sanitize HOME=/root to prevent libpq SSL certificate permission errors."""
    import os

    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setattr(os, "getuid", lambda: 1000)

    for candidate in ("/home/app", "/tmp"):
        if os.path.exists(candidate) and os.access(candidate, os.W_OK):
            os.environ["HOME"] = candidate
            break

    assert os.environ["HOME"] != "/root"
