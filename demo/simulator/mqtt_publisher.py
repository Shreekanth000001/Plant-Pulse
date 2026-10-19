"""Runs the demo manufacturing line simulation and publishes canonical MQTT topics.

Heartbeat-as-run watchdog:
- Subscribes to plants/{plant_id}/control/heartbeat.
- Runs simulation only while active viewers are connected (heartbeats present).
- Shuts down / enters idle after 30s of heartbeat silence.
- Enforces runtime cap (default 7200s, 2 hours).

Configured via environment variables:
    MQTT_HOST=localhost
    MQTT_PORT=1883
    MQTT_USER=<required>
    MQTT_PASSWORD=<required>
    MQTT_CLIENT_ID=<required>
    PLANT_ID=plant_demo_membrane
    SIMULATOR_MAX_RUNTIME_SECONDS=7200
"""

import json
import logging
import os
import signal
import time

import paho.mqtt.client as mqtt

try:
    from demo.simulator.simulator import (
        DemoSimulator,
        build_qc_result_payload,
        build_queue_depths_payload,
        build_stage_event_payload,
        build_state_payload,
        build_telemetry_payload,
        load_simulator_credentials,
    )
    from demo.simulator.watchdog import Watchdog
    from demo.simulator.water_simulator import (
        WaterPlantSimulator,
        build_water_state_payload,
        build_water_telemetry_payload,
        load_water_credentials,
    )
except ImportError:
    from watchdog import Watchdog
    from water_simulator import (
        WaterPlantSimulator,
        build_water_state_payload,
        build_water_telemetry_payload,
        load_water_credentials,
    )

    from simulator import (
        DemoSimulator,
        build_qc_result_payload,
        build_queue_depths_payload,
        build_stage_event_payload,
        build_state_payload,
        build_telemetry_payload,
        load_simulator_credentials,
    )

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("demo-simulator-publisher")

BROKER_HOST = os.getenv("MQTT_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
PLANT_ID = os.getenv("PLANT_ID", "plant_demo_membrane")
MAX_RUNTIME = float(
    os.getenv(
        "SIMULATOR_MAX_RUNTIME_SECONDS",
        os.getenv("MAX_RUNTIME_SECONDS", "7200"),
    )
)
TICK_SECONDS = 2
KEEPALIVE_S = 30
QOS = 1

stop_event_set = False
connected = False
water_connected = False
WATER_PLANT_ID = "plant_water_district_9"
WATER_TICK_SECONDS = 5.0


def create_water_mqtt_client(creds: dict[str, str]) -> mqtt.Client:
    def on_connect(client, userdata, flags, reason_code, properties=None):
        global water_connected
        if reason_code.is_failure:
            log.error("Broker refused water client connection: %s", reason_code)
            water_connected = False
        else:
            log.info(
                "Connected water client to MQTT broker at %s:%d as %s",
                BROKER_HOST,
                BROKER_PORT,
                creds["WATER_MQTT_CLIENT_ID"],
            )
            water_connected = True

    def on_disconnect(client, userdata, flags, reason_code, properties=None):
        global water_connected
        water_connected = False
        if not stop_event_set:
            log.warning(
                "Lost broker connection for water client (%s). Auto-reconnecting...",
                reason_code,
            )

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=creds["WATER_MQTT_CLIENT_ID"],
    )
    client.username_pw_set(
        username=creds["WATER_MQTT_USER"],
        password=creds["WATER_MQTT_PASSWORD"],
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def create_mqtt_client(
    creds: dict[str, str], watchdog: Watchdog, plant_id: str
) -> mqtt.Client:
    heartbeat_topic = f"plants/{plant_id}/control/heartbeat"

    def on_connect(client, userdata, flags, reason_code, properties=None):
        global connected
        if reason_code.is_failure:
            log.error("Broker refused connection: %s", reason_code)
            connected = False
        else:
            log.info("Connected to MQTT broker at %s:%d", BROKER_HOST, BROKER_PORT)
            connected = True
            client.subscribe(heartbeat_topic, qos=1)
            log.info("Subscribed to watchdog heartbeat topic: %s", heartbeat_topic)

    def on_disconnect(client, userdata, flags, reason_code, properties=None):
        global connected
        connected = False
        if not stop_event_set:
            log.warning(
                "Lost broker connection (%s). Auto-reconnecting...", reason_code
            )

    def on_message(client, userdata, msg):
        if msg.topic == heartbeat_topic:
            watchdog.on_heartbeat()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=creds["MQTT_CLIENT_ID"],
    )
    client.username_pw_set(
        username=creds["MQTT_USER"],
        password=creds["MQTT_PASSWORD"],
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def connect_with_retry(client: mqtt.Client) -> bool:
    delay = 1
    while not stop_event_set:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=KEEPALIVE_S)
            return True
        except OSError as exc:
            log.error(
                "Cannot reach broker %s:%d (%s). Retrying in %ds...",
                BROKER_HOST,
                BROKER_PORT,
                exc,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return False


def main() -> None:
    def handle_shutdown(*_):
        global stop_event_set
        stop_event_set = True

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # 1. Load credentials or fail fast
    creds = load_simulator_credentials()
    water_creds = load_water_credentials()

    # 2. Initialize Watchdog & Simulators
    watchdog = Watchdog(
        timeout_seconds=30.0,
        max_runtime_seconds=MAX_RUNTIME,
    )
    simulator = DemoSimulator(plant_id=PLANT_ID)
    water_simulator = WaterPlantSimulator(plant_id=WATER_PLANT_ID)

    # 3. Connect to MQTT for Demo Plant and Water Plant
    client = create_mqtt_client(creds, watchdog, PLANT_ID)
    if not connect_with_retry(client):
        return
    client.loop_start()

    water_client = create_water_mqtt_client(water_creds)
    if not connect_with_retry(water_client):
        client.loop_stop()
        client.disconnect()
        return
    water_client.loop_start()

    wait_elapsed = 0.0
    while (
        (not connected or not water_connected)
        and wait_elapsed < 5.0
        and not stop_event_set
    ):
        time.sleep(0.1)
        wait_elapsed += 0.1

    log.info(
        "Simulators initialized for %s and %s. Awaiting watchdog heartbeat on plants/%s/control/heartbeat...",
        PLANT_ID,
        WATER_PLANT_ID,
        PLANT_ID,
    )

    stage_by_machine = {m.machine_id: m.sub_facility for m in simulator.line.machines}
    stage_by_machine.update({q.machine_id: "qc" for q in simulator.line.qc_stations})
    prev_machine_states: dict[str, str] = {}
    prev_water_machine_states: dict[str, str] = {}
    last_water_publish = 0.0
    tick_count = 0

    try:
        while not stop_event_set:
            if not watchdog.should_run():
                time.sleep(0.5)
                continue

            # Watchdog active: generate simulation tick for demo manufacturing line
            readings = simulator.tick()

            if connected:
                for reading in readings:
                    m_code = reading["machine_id"]
                    current_state = reading["machine_state"]
                    prev_state = prev_machine_states.get(m_code)

                    # State change event
                    if prev_state is not None and prev_state != current_state:
                        s_topic, s_payload = build_state_payload(
                            PLANT_ID,
                            m_code,
                            previous_status=prev_state,
                            status=current_state,
                            sub_status=reading.get("phase"),
                        )
                        client.publish(s_topic, json.dumps(s_payload), qos=QOS)
                    prev_machine_states[m_code] = current_state

                    # Core telemetry payload
                    t_topic, t_payload = build_telemetry_payload(
                        reading, plant_id=PLANT_ID
                    )
                    client.publish(t_topic, json.dumps(t_payload), qos=QOS)

                    # Stage event if completed
                    if reading.get("stage_event"):
                        ev = reading["stage_event"]
                        se_topic, se_payload = build_stage_event_payload(
                            PLANT_ID,
                            machine_code=m_code,
                            area_code=stage_by_machine.get(m_code, "housing"),
                            unit_id=ev["unit_id"],
                            outcome=ev["outcome"],
                            anomaly_score=ev["anomaly_score"],
                            readings=ev["readings"],
                            entered_at=ev.get("entered_at"),
                            exited_at=ev.get("exited_at"),
                        )
                        client.publish(se_topic, json.dumps(se_payload), qos=QOS)

                    # QC result if tested
                    if reading.get("last_result"):
                        res = reading["last_result"]
                        qc_topic, qc_payload = build_qc_result_payload(
                            PLANT_ID,
                            machine_code=m_code,
                            unit_id=res["unit_id"],
                            outcome=res["outcome"],
                            probability=res["probability"],
                            defect_type=res.get("defect_type"),
                            attributed_stage=res.get("attributed_stage"),
                        )
                        client.publish(qc_topic, json.dumps(qc_payload), qos=QOS)

                # Periodic queue depths
                tick_count += 1
                if tick_count % 5 == 0:
                    qd_topic, qd_payload = build_queue_depths_payload(
                        PLANT_ID, simulator.queue_depths()
                    )
                    client.publish(qd_topic, json.dumps(qd_payload), qos=QOS)

            # Water plant telemetry publishing (at 5s interval, only while watchdog should_run)
            now_mono = time.monotonic()
            if water_connected and (
                now_mono - last_water_publish >= WATER_TICK_SECONDS
            ):
                water_readings = water_simulator.tick()
                for w_reading in water_readings:
                    w_code = w_reading["machine_code"]
                    w_state = w_reading["state"]
                    w_prev = prev_water_machine_states.get(w_code)

                    # State event if state changed or first emission
                    if w_prev is None or w_prev != w_state:
                        ws_topic, ws_payload = build_water_state_payload(
                            WATER_PLANT_ID,
                            w_code,
                            previous_status=w_prev,
                            status=w_state,
                        )
                        water_client.publish(ws_topic, json.dumps(ws_payload), qos=QOS)
                        prev_water_machine_states[w_code] = w_state

                    # Telemetry payload
                    wt_topic, wt_payload = build_water_telemetry_payload(
                        w_reading, plant_id=WATER_PLANT_ID
                    )
                    water_client.publish(wt_topic, json.dumps(wt_payload), qos=QOS)

                last_water_publish = now_mono

            time.sleep(TICK_SECONDS)

    finally:
        log.info("Simulator shutting down...")
        client.loop_stop()
        client.disconnect()
        water_client.loop_stop()
        water_client.disconnect()


if __name__ == "__main__":
    main()
