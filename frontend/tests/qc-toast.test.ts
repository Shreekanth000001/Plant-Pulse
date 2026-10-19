import test from "node:test";
import assert from "node:assert/strict";

import {
  parseQcResultPayload,
  safeToUpperCase,
} from "../lib/plant-utils.ts";

test("QC Result Parsing: extracts fields from canonical multi-plant envelope", () => {
  const canonicalMessage = {
    schema_version: "1.0",
    message_id: "550e8400-e29b-41d4-a716-446655440000",
    plant_id: "plant_demo_membrane",
    asset_id: "qc_01",
    device_timestamp: "2026-10-19T13:45:00.000Z",
    payload_type: "qc_result",
    payload: {
      unit_id: "M-1004",
      machine_code: "qc_01",
      outcome: "pass",
      probability: 0.995,
      defect_type: null,
      attributed_stage: null,
    },
  };

  const parsed = parseQcResultPayload(canonicalMessage);
  assert.ok(parsed, "Parsed payload should not be null");
  assert.equal(parsed.unit_id, "M-1004");
  assert.equal(parsed.outcome, "pass");
  assert.equal(parsed.probability, 0.995);
  assert.equal(parsed.defect_type, null);
  assert.equal(parsed.attributed_stage, null);
});

test("QC Result Parsing: extracts fields from flat legacy payload", () => {
  const legacyMessage = {
    unit_id: "M-1005",
    outcome: "fail",
    probability: 0.88,
    defect_type: "vibration_damage",
    attributed_stage: "housing",
  };

  const parsed = parseQcResultPayload(legacyMessage);
  assert.ok(parsed, "Parsed legacy payload should not be null");
  assert.equal(parsed.unit_id, "M-1005");
  assert.equal(parsed.outcome, "fail");
  assert.equal(parsed.probability, 0.88);
  assert.equal(parsed.defect_type, "vibration_damage");
  assert.equal(parsed.attributed_stage, "housing");
});

test("QC Result Parsing: returns null on malformed or empty payloads without outcome or unit_id", () => {
  assert.equal(parseQcResultPayload(null), null);
  assert.equal(parseQcResultPayload({}), null);
  assert.equal(parseQcResultPayload({ unit_id: "M-1006" }), null);
  assert.equal(parseQcResultPayload({ outcome: "pass" }), null);
  assert.equal(parseQcResultPayload({ payload: {} }), null);
  assert.equal(parseQcResultPayload({ payload: { unit_id: "M-1007" } }), null);
});

test("safeToUpperCase: handles undefined, null, non-strings safely without throwing", () => {
  assert.equal(safeToUpperCase(undefined), "");
  assert.equal(safeToUpperCase(null), "");
  assert.equal(safeToUpperCase(undefined, "UNKNOWN"), "UNKNOWN");
  assert.equal(safeToUpperCase(null, "UNKNOWN"), "UNKNOWN");
  assert.equal(safeToUpperCase("pass"), "PASS");
  assert.equal(safeToUpperCase("fail"), "FAIL");
  assert.equal(safeToUpperCase(123), "123");
  assert.equal(safeToUpperCase({}), "[OBJECT OBJECT]");
});

test("Defense against Uncaught TypeError: formatting undefined outcome or machine ID never throws", () => {
  // Simulating Toast item rendering logic
  const items = [
    { outcome: undefined },
    { outcome: null },
    { outcome: "" },
    { outcome: "pass" },
    { outcome: "fail" },
  ];

  for (const item of items) {
    assert.doesNotThrow(() => {
      const isPass = item.outcome?.toLowerCase() === "pass";
      const display = safeToUpperCase(item.outcome, "UNKNOWN");
      assert.ok(typeof isPass === "boolean");
      assert.ok(typeof display === "string");
    });
  }

  // Simulating Station starved / Inspector modal logic
  const machineIds = [undefined, null, "", "hm_01", "qc_01"];
  for (const mId of machineIds) {
    assert.doesNotThrow(() => {
      const displayId = (mId || "").toUpperCase();
      assert.ok(typeof displayId === "string");
    });
  }

  // Simulating sensor key formatting
  const testKeys = [undefined, null, "", "temp_mold", "vibration_level"];
  for (const key of testKeys) {
    assert.doesNotThrow(() => {
      const formatted = String(key || "")
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c) => (c ? c.toUpperCase() : ""));
      assert.ok(typeof formatted === "string");
    });
  }
});

