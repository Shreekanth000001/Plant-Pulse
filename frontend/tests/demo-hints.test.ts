import test from "node:test";
import assert from "node:assert/strict";

import { getDemoHintForPlant } from "../lib/plant-utils.ts";

test("Criterion 5: getDemoHintForPlant returns token hint when DEMO_HINTS is enabled for plant_water_district_9", () => {
  const hint = getDemoHintForPlant("plant_water_district_9", true);
  assert.notStrictEqual(hint, null);
  assert.strictEqual(hint?.token, "district9_read_secret_token_889");
  assert.match(hint?.message || "", /district9_read_secret_token_889/);
});

test("Criterion 5: getDemoHintForPlant returns null when DEMO_HINTS is disabled or unset", () => {
  assert.strictEqual(getDemoHintForPlant("plant_water_district_9", false), null);
  assert.strictEqual(getDemoHintForPlant("plant_water_district_9", undefined), null);
});

test("Criterion 5: getDemoHintForPlant returns null for public plant even if DEMO_HINTS is enabled", () => {
  assert.strictEqual(getDemoHintForPlant("plant_demo_membrane", true), null);
  assert.strictEqual(getDemoHintForPlant("some_other_plant", true), null);
});
