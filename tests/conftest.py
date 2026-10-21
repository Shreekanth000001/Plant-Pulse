"""Pytest test suite configuration and default test environment fixtures."""

import os

# Set standard test environment variables before tests import modules or load plants
os.environ.setdefault("MQTT_PASSWORD", "demo_membrane_secure_token_123")
os.environ.setdefault("WATER_MQTT_PASSWORD", "water_district_edge_key_771")
os.environ.setdefault(
    "PLANT_WATER_DISTRICT_9_VIEWER_TOKEN", "district9_read_secret_token_889"
)
os.environ.setdefault("BACKEND_MQTT_PASSWORD", "backend_test_password_123")
