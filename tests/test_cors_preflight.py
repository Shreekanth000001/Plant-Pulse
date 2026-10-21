import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing

import pytest
import uvicorn

from database import get_db_connection
from main import PLANTS_DIR, build_app, init_platform_db, seed_plants_if_empty


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


def test_cors_preflight_allows_authorization_and_crud_methods(tmp_path, monkeypatch):
    """CORS preflight (OPTIONS) must allow Authorization header and methods GET, POST, PUT, DELETE."""
    db_file = tmp_path / "platform.db"
    monkeypatch.setenv("PLATFORM_DB_PATH", str(db_file))
    monkeypatch.setattr("main.PLATFORM_DB_PATH", str(db_file))
    monkeypatch.setenv("MOUNT_ADMIN_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "test_admin_token_1234567890_32char")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")

    init_platform_db(db_file)
    conn = get_db_connection(str(db_file))
    seed_plants_if_empty(conn, PLANTS_DIR)
    conn.close()

    app = build_app()
    srv, thread, base_url = run_test_server(app)

    try:
        for method in ["GET", "POST", "PUT", "DELETE"]:
            req = urllib.request.Request(
                f"{base_url}/api/admin/plants",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
                method="OPTIONS",
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                assert resp.status == 200, (
                    f"OPTIONS for {method} returned {resp.status}"
                )
                headers = {k.lower(): v for k, v in resp.headers.items()}
                assert (
                    headers.get("access-control-allow-origin")
                    == "http://localhost:3000"
                )
                allow_methods = [
                    m.strip().upper()
                    for m in headers.get("access-control-allow-methods", "").split(",")
                ]
                assert method in allow_methods, (
                    f"Method {method} not found in Access-Control-Allow-Methods: {allow_methods}"
                )
                allow_headers = headers.get("access-control-allow-headers", "").lower()
                assert "authorization" in allow_headers or "*" in allow_headers, (
                    f"Authorization not allowed in headers: {allow_headers}"
                )
    finally:
        srv.should_exit = True
        thread.join(timeout=2.0)
