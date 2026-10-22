import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  formatPlantQuota,
  canCreatePlant,
  buildTelemetryExampleJson,
  buildMosquittoPubCommand,
} from "../lib/me-api.ts";

describe("Self-Service Plant API Helpers", () => {
  test("formatPlantQuota formats count and max correctly", () => {
    assert.equal(formatPlantQuota(0, 3), "0 of 3 plants");
    assert.equal(formatPlantQuota(1, 3), "1 of 3 plants");
    assert.equal(formatPlantQuota(2, 3), "2 of 3 plants");
    assert.equal(formatPlantQuota(3, 3), "3 of 3 plants");
    assert.equal(formatPlantQuota(1), "1 of 3 plants");
  });

  test("canCreatePlant enforces quota boundary", () => {
    assert.equal(canCreatePlant(0, 3), true);
    assert.equal(canCreatePlant(1, 3), true);
    assert.equal(canCreatePlant(2, 3), true);
    assert.equal(canCreatePlant(3, 3), false);
    assert.equal(canCreatePlant(4, 3), false);
  });

  test("buildTelemetryExampleJson produces valid JSON with canonical envelope fields", () => {
    const rawJson = buildTelemetryExampleJson("plant_test_1", "m_01", "vibration_mms");
    const parsed = JSON.parse(rawJson);

    assert.equal(parsed.schema_version, "1.0");
    assert.equal(parsed.plant_id, "plant_test_1");
    assert.equal(parsed.asset_id, "m_01");
    assert.ok(parsed.device_timestamp, "Missing device_timestamp");
    assert.equal(parsed.message_id, "msg-001");
    assert.equal(parsed.payload.status, "RUNNING");
    assert.equal(parsed.payload.metrics.vibration_mms, 42.0);
  });

  test("buildMosquittoPubCommand formats valid CLI command matching topic_router pattern", () => {
    const cmd = buildMosquittoPubCommand("plant_my_solar", "inverter_01", "dc_voltage");

    assert.ok(cmd.startsWith("docker compose exec broker mosquitto_pub"));
    assert.ok(cmd.includes("-u device_plant_my_solar"));
    assert.ok(cmd.includes("-P '<password>'"));
    assert.ok(cmd.includes("-t 'plants/plant_my_solar/assets/inverter_01/telemetry'"));
    assert.ok(cmd.includes('"schema_version":"1.0"'));
    assert.ok(cmd.includes('"plant_id":"plant_my_solar"'));
    assert.ok(cmd.includes('"asset_id":"inverter_01"'));
    assert.ok(cmd.includes('"dc_voltage":42.0'));
  });
});
