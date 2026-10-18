import shutil
import socket
import subprocess
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest

from plant_definitions import load_plants
from scripts.generate_mosquitto_auth import (
    generate_acl_content,
    generate_auth_files,
)

PLANTS_DIR = Path(__file__).resolve().parent.parent / "plants"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_generate_acl_content():
    """Criterion 1: ACL configuration generation from plants/*.json."""
    plants = load_plants(PLANTS_DIR)
    acl = generate_acl_content(plants, backend_user="backend_service")

    # Backend service must have full read/write access across all plants
    assert "user backend_service" in acl
    assert "topic readwrite plants/#" in acl

    # Each plant credential must have readwrite scoped strictly to plants/{plant_id}/#
    assert "user device_plant_demo_membrane" in acl
    assert "topic readwrite plants/plant_demo_membrane/#" in acl

    assert "user device_plant_water_district_9" in acl
    assert "topic readwrite plants/plant_water_district_9/#" in acl


def test_generate_auth_files_creates_files_with_secure_permissions(tmp_path):
    """Criterion 1: Password and ACL file generation with secure permissions."""
    passwd_path = tmp_path / "passwd"
    acl_path = tmp_path / "acl.conf"

    generate_auth_files(
        plants_dir=PLANTS_DIR,
        passwd_path=passwd_path,
        acl_path=acl_path,
        backend_user="backend_service",
        backend_password="backend_test_password_123",
    )

    assert passwd_path.exists()
    assert acl_path.exists()

    # Permissions should be restricted (0600)
    assert oct(passwd_path.stat().st_mode & 0o777) == "0o600"
    assert oct(acl_path.stat().st_mode & 0o777) == "0o600"

    passwd_content = passwd_path.read_text(encoding="utf-8")
    assert "backend_service:" in passwd_content
    assert "device_plant_demo_membrane:" in passwd_content
    assert "device_plant_water_district_9:" in passwd_content


@pytest.fixture
def mosquitto_broker(tmp_path):
    """Spins up a temporary Mosquitto instance with generated auth files."""
    if not shutil.which("mosquitto"):
        pytest.skip("mosquitto binary not found on system")

    port = get_free_port()
    passwd_path = tmp_path / "passwd"
    acl_path = tmp_path / "acl.conf"
    conf_path = tmp_path / "mosquitto.conf"

    generate_auth_files(
        plants_dir=PLANTS_DIR,
        passwd_path=passwd_path,
        acl_path=acl_path,
        backend_user="backend_service",
        backend_password="backend_service_secret",
    )

    conf_content = (
        f"listener {port} 127.0.0.1\n"
        f"allow_anonymous false\n"
        f"password_file {passwd_path}\n"
        f"acl_file {acl_path}\n"
    )
    conf_path.write_text(conf_content, encoding="utf-8")

    proc = subprocess.Popen(["mosquitto", "-c", str(conf_path)])
    time.sleep(0.5)

    try:
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_mosquitto_two_plant_acl_isolation(mosquitto_broker):
    """Criterion 2: Two-plant ACL test proves plant A cannot publish or read plant B topics."""
    port = mosquitto_broker

    received_demo = []
    received_water = []

    # Client A: Membrane Demo Plant
    client_demo = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="test_demo_client"
    )
    client_demo.username_pw_set(
        "device_plant_demo_membrane", "demo_membrane_secure_token_123"
    )
    client_demo.on_message = lambda c, u, msg: received_demo.append(msg)
    assert client_demo.connect("127.0.0.1", port, 10) == 0
    client_demo.loop_start()

    # Client B: Water District 9 Plant
    client_water = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="test_water_client"
    )
    client_water.username_pw_set(
        "device_plant_water_district_9", "water_district_edge_key_771"
    )
    client_water.on_message = lambda c, u, msg: received_water.append(msg)
    assert client_water.connect("127.0.0.1", port, 10) == 0
    client_water.loop_start()

    # Both clients subscribe to the other plant's topics (attempting cross-plant read)
    client_demo.subscribe("plants/plant_water_district_9/#", qos=1)
    client_water.subscribe("plants/plant_demo_membrane/#", qos=1)

    # Both clients also subscribe to their own topics (legitimate read)
    client_demo.subscribe("plants/plant_demo_membrane/#", qos=1)
    client_water.subscribe("plants/plant_water_district_9/#", qos=1)

    time.sleep(0.5)

    try:
        # 1. Membrane publishes legitimate message to Membrane plant
        client_demo.publish(
            "plants/plant_demo_membrane/assets/hm_01/telemetry", "demo-data", qos=1
        )
        time.sleep(0.5)

        # Membrane received its own message, Water received 0
        assert len(received_demo) == 1
        assert len(received_water) == 0

        # 2. Water publishes legitimate message to Water plant
        client_water.publish(
            "plants/plant_water_district_9/assets/pump_01/telemetry",
            "water-data",
            qos=1,
        )
        time.sleep(0.5)

        # Water received its own message, Membrane did not receive Water's message
        assert len(received_water) == 1
        assert len(received_demo) == 1

        # 3. Membrane attempts to publish to Water plant (unauthorized publish)
        client_demo.publish(
            "plants/plant_water_district_9/assets/pump_01/telemetry",
            "spoof-water",
            qos=1,
        )
        time.sleep(0.5)

        # Water must NOT receive the spoofed message
        assert len(received_water) == 1

        # 4. Water attempts to publish to Membrane plant (unauthorized publish)
        client_water.publish(
            "plants/plant_demo_membrane/assets/hm_01/telemetry", "spoof-demo", qos=1
        )
        time.sleep(0.5)

        # Membrane must NOT receive the spoofed message
        assert len(received_demo) == 1

    finally:
        client_demo.loop_stop()
        client_demo.disconnect()
        client_water.loop_stop()
        client_water.disconnect()


def test_mosquitto_backend_service_full_access(mosquitto_broker):
    """Criterion 2: Backend service can subscribe and publish across all plants."""
    port = mosquitto_broker

    received_backend = []
    backend_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="backend_service_client"
    )
    backend_client.username_pw_set("backend_service", "backend_service_secret")
    backend_client.on_message = lambda c, u, msg: received_backend.append(msg)
    assert backend_client.connect("127.0.0.1", port, 10) == 0
    backend_client.loop_start()

    backend_client.subscribe("plants/#", qos=1)
    time.sleep(0.3)

    client_demo = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pub_demo")
    client_demo.username_pw_set(
        "device_plant_demo_membrane", "demo_membrane_secure_token_123"
    )
    assert client_demo.connect("127.0.0.1", port, 10) == 0
    client_demo.loop_start()

    client_water = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pub_water")
    client_water.username_pw_set(
        "device_plant_water_district_9", "water_district_edge_key_771"
    )
    assert client_water.connect("127.0.0.1", port, 10) == 0
    client_water.loop_start()

    try:
        client_demo.publish(
            "plants/plant_demo_membrane/assets/hm_01/telemetry", "payload-demo", qos=1
        )
        client_water.publish(
            "plants/plant_water_district_9/assets/pump_01/telemetry",
            "payload-water",
            qos=1,
        )
        time.sleep(0.5)

        assert len(received_backend) == 2
        topics = {msg.topic for msg in received_backend}
        assert "plants/plant_demo_membrane/assets/hm_01/telemetry" in topics
        assert "plants/plant_water_district_9/assets/pump_01/telemetry" in topics
    finally:
        backend_client.loop_stop()
        backend_client.disconnect()
        client_demo.loop_stop()
        client_demo.disconnect()
        client_water.loop_stop()
        client_water.disconnect()


def test_mosquitto_unauthenticated_and_wrong_password_rejected(mosquitto_broker):
    """Criterion 3: Unauthenticated connections and incorrect passwords are rejected."""
    port = mosquitto_broker

    # Anonymous connection rejected
    anon_reasons = []
    client_anon = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="anon_client")
    client_anon.on_connect = lambda c, u, flags, rc, props: anon_reasons.append(rc)
    client_anon.connect("127.0.0.1", port, 5)
    client_anon.loop_start()
    time.sleep(0.5)

    assert len(anon_reasons) == 1
    assert anon_reasons[0].is_failure
    assert not client_anon.is_connected()
    client_anon.loop_stop()
    client_anon.disconnect()

    # Bad password rejected
    bad_reasons = []
    client_bad = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bad_client")
    client_bad.username_pw_set("device_plant_demo_membrane", "wrong_password_here")
    client_bad.on_connect = lambda c, u, flags, rc, props: bad_reasons.append(rc)
    client_bad.connect("127.0.0.1", port, 5)
    client_bad.loop_start()
    time.sleep(0.5)

    assert len(bad_reasons) == 1
    assert bad_reasons[0].is_failure
    assert not client_bad.is_connected()
    client_bad.loop_stop()
    client_bad.disconnect()
