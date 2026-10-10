"""
Runs the full production Line and publishes every reading to MQTT.

Topics:
    factory/{sub_facility}/{machine_id}/telemetry  — every machine, every tick
    factory/{sub_facility}/{machine_id}/stage_event — when a machine completes a unit's stage
    factory/qc/{machine_id}/result                 — only when QC finishes testing a unit
    factory/queue_depths                           — current queue sizes, published periodically

Same connect/retry/reconnect pattern as the very first edge-agent script
in this project — same problem (publish readings reliably over MQTT),
just a different, richer data source underneath.

Requirements:
    pip install paho-mqtt>=2.0

Config via environment variables:
    MQTT_HOST=localhost   MQTT_PORT=1883
"""

import json
import logging
import os
import signal
import time

import paho.mqtt.client as mqtt

from simulator import Line

BROKER_HOST = os.getenv("MQTT_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
TICK_SECONDS = 2
KEEPALIVE_S = 30
QOS = 1

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("factory-publisher")

stop_event_set = False
connected = False


def on_connect(client, userdata, flags, reason_code, properties):
    global connected
    if reason_code.is_failure:
        log.error("Broker refused connection: %s", reason_code)
        connected = False
    else:
        log.info("Connected to MQTT broker at %s:%d", BROKER_HOST, BROKER_PORT)
        connected = True


def on_disconnect(client, userdata, flags, reason_code, properties):
    global connected
    connected = False
    if not stop_event_set:
        log.warning("Lost broker connection (%s). Auto-reconnecting...", reason_code)


def build_client() -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="factory-line-publisher",
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def connect_with_retry(client: mqtt.Client) -> bool:
    delay = 1
    while not stop_event_set:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=KEEPALIVE_S)
            return True
        except OSError as exc:
            log.error("Cannot reach broker %s:%d (%s). Retrying in %ds...",
                       BROKER_HOST, BROKER_PORT, exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return False


def publish_reading(client: mqtt.Client, reading: dict, sub_facility: str) -> None:
    machine_id = reading["machine_id"]

    if sub_facility == "qc":
        if reading.get("last_result"):
            topic = f"factory/qc/{machine_id}/result"
            client.publish(topic, json.dumps(reading["last_result"]), qos=QOS)
        topic = f"factory/qc/{machine_id}/telemetry"
    else:
        # A production machine may have just completed a unit's stage
        # this tick — if so, publish that separately so the backend can
        # store the full traceability history, not just QC's final verdict.
        if reading.get("stage_event"):
            event_topic = f"factory/{sub_facility}/{machine_id}/stage_event"
            client.publish(event_topic, json.dumps(reading["stage_event"]), qos=QOS)
        topic = f"factory/{sub_facility}/{machine_id}/telemetry"

    client.publish(topic, json.dumps(reading), qos=QOS)


def main() -> None:

    def handle_shutdown(*_):
        global stop_event_set
        stop_event_set = True

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    client = build_client()
    if not connect_with_retry(client):
        return
    client.loop_start()

    # connect() only opens the TCP connection; the actual CONNACK (which
    # flips `connected` True via on_connect) arrives asynchronously on
    # loop_start()'s background thread. Wait for it before publishing,
    # or the first several ticks get silently skipped.
    wait_elapsed = 0.0
    while not connected and wait_elapsed < 5.0:
        time.sleep(0.1)
        wait_elapsed += 0.1
    if not connected:
        log.warning("Still not confirmed connected after 5s — proceeding anyway, "
                    "early ticks may be skipped until it catches up.")

    line = Line()
    # machine_id -> sub_facility, so publish_reading knows which topic to use
    stage_by_machine = {m.machine_id: m.sub_facility for m in line.machines}
    stage_by_machine.update({q.machine_id: "qc" for q in line.qc_stations})

    log.info("Publishing %d machines to MQTT. Ctrl+C to stop.",
              len(line.machines) + len(line.qc_stations))

    try:
        while not stop_event_set:
            for reading in line.tick():
                if connected:
                    publish_reading(client, reading, stage_by_machine[reading["machine_id"]])
                else:
                    log.warning("Broker unavailable; skipping this tick's publish.")

            if connected:
                client.publish("factory/queue_depths", json.dumps(line.queue_depths()), qos=QOS)

            time.sleep(TICK_SECONDS)
    finally:
        log.info("Shutting down...")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()