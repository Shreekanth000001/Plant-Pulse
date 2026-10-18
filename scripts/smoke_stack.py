#!/usr/bin/env python3
"""Smoke test script for PlantPulse Docker Compose stack.

Validates end-to-end functionality strictly via external HTTP and WebSocket interfaces:
1. Checks GET /health returns {"status": "ok"}.
2. Checks GET /api/plants returns 2 plants.
3. Opens WebSocket connection to /ws/plant_demo_membrane/telemetry to trigger heartbeats.
4. Polls GET /api/plants/plant_demo_membrane/machines/latest until non-empty signal values
   appear within 90 seconds.

Usage:
    python scripts/smoke_stack.py [--api-url http://localhost:8000] [--timeout 90]
"""

import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request

import websockets


def check_http_endpoint(url: str, description: str, timeout: float = 5.0) -> dict | list:
    """Perform a synchronous GET request and return parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": "PlantPulse-SmokeTest"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{description} returned HTTP {response.status}")
        data = response.read().decode("utf-8")
        return json.loads(data)


async def run_smoke_test(api_url: str, ws_url: str, timeout_seconds: float = 90.0) -> None:
    print(f"[smoke] Checking health at {api_url}/health ...")
    health = check_http_endpoint(f"{api_url}/health", "Health endpoint")
    if health.get("status") != "ok":
        raise RuntimeError(f"Expected health status 'ok', got: {health}")
    print("[smoke] Healthcheck passed: status is ok")

    print(f"[smoke] Checking plant list at {api_url}/api/plants ...")
    plants = check_http_endpoint(f"{api_url}/api/plants", "Plants endpoint")
    if not isinstance(plants, list) or len(plants) != 2:
        raise RuntimeError(f"Expected 2 plants from /api/plants, got {len(plants) if isinstance(plants, list) else plants}")
    plant_ids = {p.get("plant_id") for p in plants}
    expected_ids = {"plant_demo_membrane", "plant_water_district_9"}
    if plant_ids != expected_ids:
        raise RuntimeError(f"Expected plant IDs {expected_ids}, got {plant_ids}")
    print(f"[smoke] Plant registry verified: {sorted(plant_ids)}")

    print(f"[smoke] Opening WebSocket connection to {ws_url} to activate heartbeats...")
    async with websockets.connect(ws_url) as ws:
        print("[smoke] WebSocket connected! Waiting for simulator to wake and publish telemetry...")
        deadline = time.time() + timeout_seconds
        received_frames = 0
        populated_machines = []

        async def listen_ws():
            nonlocal received_frames
            try:
                while True:
                    await ws.recv()
                    received_frames += 1
            except (asyncio.CancelledError, websockets.ConnectionClosed):
                pass

        listener_task = asyncio.create_task(listen_ws())

        try:
            latest_url = f"{api_url}/api/plants/plant_demo_membrane/machines/latest"
            while time.time() < deadline:
                try:
                    machines = check_http_endpoint(latest_url, "Latest machines endpoint")
                    if isinstance(machines, list) and len(machines) > 0:
                        with_signals = [
                            m for m in machines
                            if m.get("signals") and len(m["signals"]) > 0
                        ]
                        if with_signals:
                            populated_machines = with_signals
                            break
                except Exception as err:  # noqa: BLE001
                    print(f"[smoke] Polling notice: {err}")

                await asyncio.sleep(2.0)
                elapsed = int(time.time() - (deadline - timeout_seconds))
                print(f"[smoke] Waiting for telemetry values... ({elapsed}s elapsed, {received_frames} ws frames)")

            if not populated_machines:
                raise TimeoutError(
                    f"Timed out after {timeout_seconds}s waiting for /machines/latest to return non-empty signal values."
                )

            print(f"[smoke] SUCCESS! Found {len(populated_machines)} machine(s) with active signals:")
            for m in populated_machines[:3]:
                sig_summary = {k: v.get("value") for k, v in list(m.get("signals", {}).items())[:3]}
                print(f"  - Machine '{m.get('machine_code')}' ({m.get('state')}): signals={sig_summary}")

        finally:
            listener_task.cancel()
            await asyncio.gather(listener_task, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="PlantPulse stack smoke test")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Base URL of FastAPI service")
    parser.add_argument("--ws-url", default="ws://localhost:8000/ws/plant_demo_membrane/telemetry", help="WebSocket URL for demo plant")
    parser.add_argument("--timeout", type=float, default=90.0, help="Max seconds to wait for telemetry to appear")
    args = parser.parse_args()

    try:
        asyncio.run(run_smoke_test(api_url=args.api_url.rstrip("/"), ws_url=args.ws_url, timeout_seconds=args.timeout))
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
