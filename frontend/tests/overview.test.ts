import test from "node:test";
import assert from "node:assert/strict";

import {
  shouldShowLineIsFillingBanner,
  formatSignalReading,
  isModuleEnabled,
  buildAreaOverview,
  handleWsCloseState,
  safeLocalStorageGet,
  safeLocalStorageSet,
} from "../lib/plant-utils.ts";
import {
  fetchPlants,
  fetchPlantDefinition,
  fetchPlantMachinesLatest,
  fetchPlantQueueDepths,
  getWsUrl,
} from "../lib/api.ts";
import type {
  PublicPlantDefinition,
  PlantMachineLatest,
} from "../types/factory.ts";

test("Criterion 1: Banner 'line is filling' depends on data only (quality_inspection enabled and 0 QC results)", () => {
  assert.equal(
    shouldShowLineIsFillingBanner({
      enabledModules: ["core", "alarms", "product_traceability", "quality_inspection"],
      qcResultCount: 0,
    }),
    true,
    "Should show banner when quality_inspection is enabled and qcResultCount is 0"
  );

  assert.equal(
    shouldShowLineIsFillingBanner({
      enabledModules: ["core", "alarms", "product_traceability", "quality_inspection"],
      qcResultCount: 3,
    }),
    false,
    "Should not show banner when qcResultCount > 0"
  );

  assert.equal(
    shouldShowLineIsFillingBanner({
      enabledModules: ["core", "alarms"],
      qcResultCount: 0,
    }),
    false,
    "Should not show banner when quality_inspection is not enabled"
  );

  assert.equal(
    shouldShowLineIsFillingBanner({
      enabledModules: ["core", "quality_inspection"],
      qcResultCount: 0,
    }),
    true,
    "Should work for any arbitrary plant definition without plant id check"
  );
});

test("Criterion 2: Plant with no telemetry yet shows 'no data yet', never blank or NaN", () => {
  assert.equal(formatSignalReading(undefined, "bar"), "no data yet");
  assert.equal(formatSignalReading(null, "°C"), "no data yet");
  assert.equal(formatSignalReading(NaN, "mm/s"), "no data yet");
  assert.equal(formatSignalReading("", "A"), "no data yet");

  assert.equal(formatSignalReading(4.123, "bar"), "4.12 bar");
  assert.equal(formatSignalReading(0, "°C"), "0.00 °C");
  assert.equal(formatSignalReading(100, "%"), "100.00 %");

  assert.equal(formatSignalReading("RUNNING"), "RUNNING");
});

test("Criterion 3: Fetch layer confirms has_viewer_token is boolean and no token/hash/password leaks", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const urlStr = String(input);
      if (urlStr.endsWith("/api/plants")) {
        return new Response(
          JSON.stringify([
            {
              plant_id: "plant_demo_membrane",
              name: "Membrane Facility",
              timezone: "America/Chicago",
              has_viewer_token: false,
              enabled_modules: ["core", "alarms", "product_traceability", "quality_inspection"],
            },
            {
              plant_id: "plant_water_district_9",
              name: "District 9 Water Station",
              timezone: "America/New_York",
              has_viewer_token: true,
              enabled_modules: ["core", "alarms"],
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (urlStr.endsWith("/api/plants/plant_water_district_9/definition")) {
        return new Response(
          JSON.stringify({
            plant_id: "plant_water_district_9",
            name: "District 9 Water Station",
            timezone: "America/New_York",
            has_viewer_token: true,
            enabled_modules: ["core", "alarms"],
            areas: [
              {
                area_code: "pump_house",
                name: "Primary Pump House",
                display_order: 1,
                machines: [],
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (urlStr.endsWith("/api/plants/plant_water_district_9/machines/latest")) {
        return new Response(
          JSON.stringify([
            {
              machine_code: "pump_01",
              area_code: "pump_house",
              name: "Main Intake Pump P-101",
              state: "RUNNING",
              signals: {},
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      throw new Error(`Unhandled URL: ${urlStr}`);
    }) as typeof fetch;

    const plants = await fetchPlants();
    assert.equal(plants.length, 2);
    for (const p of plants) {
      assert.equal(typeof p.has_viewer_token, "boolean");
      const dump = JSON.stringify(p);
      assert.equal(dump.includes("viewer_token_hash"), false);
      assert.equal(dump.includes("password"), false);
      assert.equal(dump.includes("mqtt_credentials"), false);
    }

    const def = await fetchPlantDefinition("plant_water_district_9");
    assert.equal(typeof def.has_viewer_token, "boolean");
    assert.equal(def.has_viewer_token, true);
    const defDump = JSON.stringify(def);
    assert.equal(defDump.includes("viewer_token_hash"), false);
    assert.equal(defDump.includes("password"), false);
    assert.equal(defDump.includes("mqtt_credentials"), false);
    assert.equal("viewer_token" in def, false);

    const latest = await fetchPlantMachinesLatest("plant_water_district_9");
    assert.equal(latest.length, 1);
    assert.equal(latest[0].machine_code, "pump_01");

    // Dynamic WS URL check
    assert.equal(getWsUrl("plant_water_district_9"), "ws://localhost:8000/ws/plant_water_district_9/telemetry");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Criterion 4: Module gating hides traceability and quality when disabled in enabled_modules", () => {
  const membraneModules = ["core", "alarms", "product_traceability", "quality_inspection"];
  const waterModules = ["core", "alarms"];

  assert.equal(isModuleEnabled(membraneModules, "product_traceability"), true);
  assert.equal(isModuleEnabled(membraneModules, "quality_inspection"), true);

  assert.equal(isModuleEnabled(waterModules, "product_traceability"), false);
  assert.equal(isModuleEnabled(waterModules, "quality_inspection"), false);
  assert.equal(isModuleEnabled(waterModules, "core"), true);
  assert.equal(isModuleEnabled(waterModules, "alarms"), true);
});

test("Criterion 5: Dynamic overview builds areas and machines from definition without hardcoded types", () => {
  const waterDefinition: PublicPlantDefinition = {
    plant_id: "plant_water_district_9",
    name: "District 9 Water Booster Station",
    timezone: "America/New_York",
    has_viewer_token: true,
    enabled_modules: ["core", "alarms"],
    areas: [
      {
        area_code: "pump_house",
        name: "Primary Pump House",
        display_order: 1,
        machines: [
          {
            machine_code: "pump_02",
            name: "Secondary Booster P-102",
            display_order: 2,
            signals: [
              { signal_code: "discharge_pressure_bar", name: "Discharge Pressure", unit: "bar", data_type: "float", display_order: 1 },
            ],
          },
          {
            machine_code: "pump_01",
            name: "Main Intake Pump P-101",
            display_order: 1,
            signals: [
              { signal_code: "discharge_pressure_bar", name: "Discharge Pressure", unit: "bar", data_type: "float", display_order: 1 },
              { signal_code: "flow_rate_m3h", name: "Water Flow Rate", unit: "m³/h", data_type: "float", display_order: 2 },
            ],
          },
        ],
      },
    ],
  };

  const waterMachinesLatest: PlantMachineLatest[] = [
    {
      machine_code: "pump_01",
      area_code: "pump_house",
      name: "Main Intake Pump P-101",
      state: "RUNNING",
      signals: {
        discharge_pressure_bar: { value: 4.15, value_num: 4.15, device_timestamp: "2026-10-18T10:00:00Z" },
        flow_rate_m3h: { value: 152.4, value_num: 152.4, device_timestamp: "2026-10-18T10:00:00Z" },
      },
    },
    {
      machine_code: "pump_02",
      area_code: "pump_house",
      name: "Secondary Booster P-102",
      state: "IDLE",
      signals: {},
    },
  ];

  const overview = buildAreaOverview(waterDefinition, waterMachinesLatest);
  assert.equal(overview.length, 1);
  assert.equal(overview[0].area_code, "pump_house");
  assert.equal(overview[0].name, "Primary Pump House");

  assert.equal(overview[0].machines.length, 2);
  assert.equal(overview[0].machines[0].machine_code, "pump_01");
  assert.equal(overview[0].machines[1].machine_code, "pump_02");

  assert.equal(overview[0].machines[0].state, "RUNNING");
  assert.equal(overview[0].machines[0].signals[0].signal_code, "discharge_pressure_bar");
  assert.equal(overview[0].machines[0].signals[0].formattedValue, "4.15 bar");

  assert.equal(overview[0].machines[1].state, "IDLE");
  assert.equal(overview[0].machines[1].signals[0].formattedValue, "no data yet");
});

test("Criterion 6: WebSocket code 4401 transitions to 'token_required' and falls back to 5s polling", () => {
  const normalResult = handleWsCloseState(1006);
  assert.equal(normalResult.status, "reconnecting");
  assert.equal(normalResult.shouldReconnect, true);
  assert.equal(normalResult.isTokenRequired, false);
  assert.equal(normalResult.fallbackPollingIntervalMs, null);

  const tokenResult = handleWsCloseState(4401);
  assert.equal(tokenResult.status, "token_required");
  assert.equal(tokenResult.shouldReconnect, false);
  assert.equal(tokenResult.isTokenRequired, true);
  assert.equal(tokenResult.fallbackPollingIntervalMs, 5000);
});

test("Criterion 7: localStorage reads and writes are safely wrapped in try/catch", () => {
  const mockStorage: Record<string, string> = {};
  const mockLocalStorage: Storage = {
    length: 0,
    clear: () => {},
    key: () => null,
    removeItem: () => {},
    getItem: (key: string) => mockStorage[key] ?? null,
    setItem: (key: string, val: string) => { mockStorage[key] = val; },
  };

  assert.equal(safeLocalStorageGet("my_key", "default_val", mockLocalStorage), "default_val");
  safeLocalStorageSet("my_key", "stored_val", mockLocalStorage);
  assert.equal(safeLocalStorageGet("my_key", "default_val", mockLocalStorage), "stored_val");

  const brokenLocalStorage: Storage = {
    length: 0,
    clear: () => {},
    key: () => null,
    removeItem: () => {},
    getItem: () => { throw new Error("SecurityError: Access denied"); },
    setItem: () => { throw new Error("QuotaExceededError"); },
  };

  assert.doesNotThrow(() => {
    const val = safeLocalStorageGet("my_key", "fallback_val", brokenLocalStorage);
    assert.equal(val, "fallback_val");
  });

  assert.doesNotThrow(() => {
    safeLocalStorageSet("my_key", "fail_val", brokenLocalStorage);
  });
});

test("Criterion 8: Machine with no state reported defaults to 'OFFLINE'", () => {
  const definition: PublicPlantDefinition = {
    plant_id: "plant_demo_membrane",
    name: "Membrane Facility",
    timezone: "America/Chicago",
    has_viewer_token: false,
    enabled_modules: ["core"],
    areas: [
      {
        area_code: "housing",
        name: "Housing Area",
        display_order: 1,
        machines: [
          {
            machine_code: "hm_01",
            name: "Housing Machine 1",
            display_order: 1,
            signals: [],
          },
        ],
      },
    ],
  };

  const overview = buildAreaOverview(definition, []);
  assert.equal(overview[0].machines[0].state, "OFFLINE");
});

test("fetchPlantQueueDepths sends Authorization header when token provided and handles 404/401", async () => {
  const originalFetch = globalThis.fetch;
  let capturedUrl = "";
  let capturedHeaders: Record<string, string> = {};

  try {
    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      capturedUrl = url.toString();
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      if (capturedUrl.includes("unauthorized_plant")) {
        return new Response("Unauthorized", { status: 401, statusText: "Unauthorized" });
      }
      if (capturedUrl.includes("no_traceability")) {
        return new Response("Not Found", { status: 404, statusText: "Not Found" });
      }
      return new Response(JSON.stringify({ casting: 5, assembly: 3, qc: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    const res = await fetchPlantQueueDepths("plant_demo_membrane", "test-token");
    assert.deepEqual(res, { casting: 5, assembly: 3, qc: 1 });
    assert.equal(capturedUrl.endsWith("/api/plants/plant_demo_membrane/queue-depths"), true);
    assert.equal(capturedHeaders["Authorization"], "Bearer test-token");

    // Check 401 error throws ApiError
    await assert.rejects(
      async () => {
        await fetchPlantQueueDepths("unauthorized_plant");
      },
      (err: unknown) => (err as { status?: number }).status === 401
    );

    // Check 404 error throws ApiError
    await assert.rejects(
      async () => {
        await fetchPlantQueueDepths("no_traceability");
      },
      (err: unknown) => (err as { status?: number }).status === 404
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
