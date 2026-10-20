import test from "node:test";
import assert from "node:assert/strict";
import { parseTelemetryPayload } from "../lib/plant-utils.ts";
import { mapBackendQueueDepths } from "../types/factory.ts";

test("Telemetry Envelope: extracts status, sub_status, vibration, and metrics from nested canonical payload", () => {
  // Real telemetry envelope fixture matching Section 4.2 / demo simulator output
  const canonicalEnvelope = {
    schema_version: "1.0",
    message_id: "936d5a8c-e66c-4876-8025-b82b99216091",
    plant_id: "plant_demo_membrane",
    asset_id: "hm_01",
    device_timestamp: "2026-10-20T05:30:00.000Z",
    payload_type: "telemetry",
    payload: {
      status: "RUNNING",
      sub_status: "FORMING",
      metrics: {
        vibration_mms: 6.32,
        hydraulic_pressure_bar: 120.5,
        mold_temperature_actual: 68.4,
      },
    },
  };

  const parsed = parseTelemetryPayload(canonicalEnvelope);
  assert.equal(parsed.status, "RUNNING");
  assert.equal(parsed.sub_status, "FORMING");
  assert.equal(parsed.vibration, 6.32);
  assert.equal(parsed.readings.hydraulic_pressure_bar, 120.5);
  assert.equal(parsed.readings.mold_temperature_actual, 68.4);
});

test("Telemetry Envelope: falls back to flat payload when envelope is unnested", () => {
  const flatPayload = {
    status: "IDLE",
    sub_status: "STANDBY",
    vibration: 0.25,
    temperature: 42.0,
  };

  const parsed = parseTelemetryPayload(flatPayload);
  assert.equal(parsed.status, "IDLE");
  assert.equal(parsed.sub_status, "STANDBY");
  assert.equal(parsed.vibration, 0.25);
  assert.equal(parsed.readings.temperature, 42.0);
});

test("Telemetry Envelope: handles missing or malformed payload gracefully without crashing", () => {
  assert.deepEqual(parseTelemetryPayload(null), { readings: {} });
  assert.deepEqual(parseTelemetryPayload(undefined), { readings: {} });
  assert.deepEqual(parseTelemetryPayload("not-an-object"), { readings: {} });
});

test("Queue Depths: correctly maps queue depth from nested canonical envelope and flat dictionary", () => {
  const canonicalQueueEnvelope = {
    schema_version: "1.0",
    message_id: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    plant_id: "plant_demo_membrane",
    device_timestamp: "2026-10-20T05:30:00.000Z",
    payload_type: "queue_depths",
    payload: {
      casting: 3,
      assembly: 1,
      qc: 2,
    },
  };

  const mappedCanonical = mapBackendQueueDepths(canonicalQueueEnvelope as unknown as Parameters<typeof mapBackendQueueDepths>[0]);
  assert.equal(mappedCanonical.housingToCasting, 3);
  assert.equal(mappedCanonical.castingToAssembly, 1);
  assert.equal(mappedCanonical.assemblyToQc, 2);

  const flatQueue = {
    casting: 5,
    assembly: 0,
    qc: 4,
  };

  const mappedFlat = mapBackendQueueDepths(flatQueue);
  assert.equal(mappedFlat.housingToCasting, 5);
  assert.equal(mappedFlat.castingToAssembly, 0);
  assert.equal(mappedFlat.assemblyToQc, 4);
});
