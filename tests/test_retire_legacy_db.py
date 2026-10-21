import asyncio
import json
import os
import sqlite3
import subprocess
import sys

import websockets

from tests.test_plant_scoped_api import http_get_raw

pytest_plugins = ["tests.test_plant_scoped_api"]

WATER_BEARER = "district9_read_secret_token_889"


def test_legacy_routes_return_404_and_ws_refuses(server):
    """Legacy routes /api/machines/latest, /api/queue-depths, /api/stats/* must return 404,
    and legacy /ws/telemetry must be refused.
    """
    base_url = server["base_url"]

    # 1. /api/machines/latest -> 404
    status, body = http_get_raw(f"{base_url}/api/machines/latest")
    assert status == 404, f"Expected 404 for /api/machines/latest, got {status}: {body}"

    # 2. /api/queue-depths -> 404
    status, body = http_get_raw(f"{base_url}/api/queue-depths")
    assert status == 404, f"Expected 404 for /api/queue-depths, got {status}: {body}"

    # 3. /api/stats/defect-rate-by-hour -> 404
    status, body = http_get_raw(f"{base_url}/api/stats/defect-rate-by-hour")
    assert status == 404, f"Expected 404 for /api/stats/defect-rate-by-hour, got {status}: {body}"

    # 4. /api/stats/defect-rate-by-stage -> 404
    status, body = http_get_raw(f"{base_url}/api/stats/defect-rate-by-stage")
    assert status == 404, f"Expected 404 for /api/stats/defect-rate-by-stage, got {status}: {body}"

    # 5. /ws/telemetry -> rejected / 404
    ws_url = f"{server['ws_url']}/ws/telemetry"

    async def try_legacy_ws():
        try:
            async with websockets.connect(ws_url):
                return "connected"
        except websockets.exceptions.InvalidStatusCode as e:
            return e.status_code
        except (websockets.exceptions.WebSocketException, OSError) as e:
            return str(type(e))

    res = asyncio.run(try_legacy_ws())
    assert res != "connected", f"Legacy /ws/telemetry should be refused, but connected successfully! Result: {res}"


def test_plant_stats_401_without_token_on_water_plant(server):
    """Plant stats return 401 without viewer token on water plant, and 200 with it."""
    base_url = server["base_url"]

    # Hourly stats: 401 without token
    status, body = http_get_raw(
        f"{base_url}/api/plants/plant_water_district_9/stats/defect-rate-by-hour"
    )
    assert status == 401, f"Expected 401 for water plant stats without token, got {status}: {body}"

    # Stage stats: 401 without token
    status, body = http_get_raw(
        f"{base_url}/api/plants/plant_water_district_9/stats/defect-rate-by-stage"
    )
    assert status == 401, f"Expected 401 for water plant stage stats without token, got {status}: {body}"

    # Hourly stats: 200 with token
    status, body = http_get_raw(
        f"{base_url}/api/plants/plant_water_district_9/stats/defect-rate-by-hour",
        headers={"Authorization": f"Bearer {WATER_BEARER}"},
    )
    assert status == 200, f"Expected 200 with token, got {status}: {body}"
    data = json.loads(body)
    assert isinstance(data, list)

    # Stage stats: 200 with token
    status, body = http_get_raw(
        f"{base_url}/api/plants/plant_water_district_9/stats/defect-rate-by-stage",
        headers={"Authorization": f"Bearer {WATER_BEARER}"},
    )
    assert status == 200, f"Expected 200 with token, got {status}: {body}"
    data = json.loads(body)
    assert isinstance(data, list)


def test_plant_stats_isolate_plants(server):
    """Plant stats for Plant A must exclude rows from Plant B."""
    import main
    conn = sqlite3.connect(main.PLATFORM_DB_PATH)
    try:
        # Seed test data for both plants
        with conn:
            # Ensure units exist
            conn.execute(
                "INSERT OR IGNORE INTO units (plant_id, unit_id, status) VALUES ('plant_demo_membrane', 'unit_iso_demo_1', 'failed');"
            )
            conn.execute(
                "INSERT OR IGNORE INTO units (plant_id, unit_id, status) VALUES ('plant_water_district_9', 'unit_iso_water_1', 'failed');"
            )
            # Insert qc_results for demo plant
            conn.execute(
                """
                INSERT OR REPLACE INTO qc_results (
                    plant_id, unit_id, machine_code, message_id, tested_at, outcome, probability, defect_type, attributed_stage
                ) VALUES (
                    'plant_demo_membrane', 'unit_iso_demo_1', 'qc_01', 'msg_demo_iso_1', '2026-10-21T10:00:00Z', 'fail', 0.95, 'crack', 'casting'
                );
                """
            )
            # Insert qc_results for water plant
            conn.execute(
                """
                INSERT OR REPLACE INTO qc_results (
                    plant_id, unit_id, machine_code, message_id, tested_at, outcome, probability, defect_type, attributed_stage
                ) VALUES (
                    'plant_water_district_9', 'unit_iso_water_1', 'pump_01', 'msg_water_iso_1', '2026-10-21T11:00:00Z', 'fail', 0.99, 'leak', 'pump_house'
                );
                """
            )
    finally:
        conn.close()

    base_url = server["base_url"]
    # Check demo plant stage stats: must only contain 'casting', not 'pump_house'
    status, body = http_get_raw(f"{base_url}/api/plants/plant_demo_membrane/stats/defect-rate-by-stage")
    assert status == 200, f"Demo stage stats failed with {status}: {body}"
    demo_stages = json.loads(body)
    stage_names = [s["stage"] for s in demo_stages]
    assert "casting" in stage_names
    assert "pump_house" not in stage_names, f"Demo plant leaked water plant stages! {stage_names}"

    # Check water plant stage stats: must only contain 'pump_house', not 'casting'
    status, body = http_get_raw(
        f"{base_url}/api/plants/plant_water_district_9/stats/defect-rate-by-stage",
        headers={"Authorization": f"Bearer {WATER_BEARER}"},
    )
    assert status == 200, f"Water stage stats failed with {status}: {body}"
    water_stages = json.loads(body)
    w_stage_names = [s["stage"] for s in water_stages]
    assert "pump_house" in w_stage_names
    assert "casting" not in w_stage_names, f"Water plant leaked demo plant stages! {w_stage_names}"


def test_grep_shows_zero_database_imports_and_import_main():
    """`python -c 'import main'` works and grep shows zero references to importing from database."""
    # Check that database.py does not exist
    assert not os.path.exists("database.py"), "database.py should be deleted"

    # Check grep across repo for 'from database import' and 'import database'
    res = subprocess.run(
        ["git", "grep", "-E", "from database import|import database"],
        check=False,
        capture_output=True,
        text=True,
    )
    # Output must be empty
    assert res.stdout.strip() == "", f"Found remaining database imports:\n{res.stdout}"

    # Check that python -c 'import main' succeeds
    py_res = subprocess.run(
        [sys.executable, "-c", "import main"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert py_res.returncode == 0, f"Failed to import main:\n{py_res.stderr}"
