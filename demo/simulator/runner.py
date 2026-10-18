"""Runnable entry point for the demo simulator client.

Usage:
    MQTT_HOST=localhost \
    MQTT_PORT=1883 \
    MQTT_USER=device_plant_demo_membrane \
    MQTT_PASSWORD=demo_membrane_secure_token_123 \
    MQTT_CLIENT_ID=client_demo_membrane_sim \
    python -m demo.simulator.runner
"""

from demo.simulator.mqtt_publisher import main as publisher_main


def main() -> None:
    """Run the externalized demo simulator client."""
    publisher_main()


if __name__ == "__main__":
    main()
