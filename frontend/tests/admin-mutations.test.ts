import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  credentialModalReducer,
  initialCredentialModalState,
  mapFastApi422Errors,
  createAdminPlant,
  rotateAdminDeviceCredentials,
  updateAdminPlant,
  deleteAdminPlant,
  diffPlantRemovals,
  parse409Removals,
  canConfirmDelete,
  isSystemPlant,
  parsePlantJson,
  validatePlantDefinitionAdvisory,
  exportPlantDefinitionJson,
  type FastApiValidationErrorDetail,
} from "../lib/admin-api.ts";

test("Credential Reducer: initial state has null credentials and is closed", () => {
  assert.strictEqual(initialCredentialModalState.isOpen, false);
  assert.strictEqual(initialCredentialModalState.credentials, null);
  assert.strictEqual(initialCredentialModalState.source, null);
});

test("Credential Reducer: state is null after create modal close", () => {
  // Step 1: Open modal with newly created plant credentials
  const openAction = {
    type: "OPEN_CREDENTIALS" as const,
    source: "create" as const,
    credentials: [
      {
        username: "device_plant_test",
        password: "secret_initial_password_123",
        client_id: "client_plant_test",
      },
    ],
  };
  const openedState = credentialModalReducer(initialCredentialModalState, openAction);
  assert.strictEqual(openedState.isOpen, true);
  assert.strictEqual(openedState.credentials?.length, 1);
  assert.strictEqual(openedState.credentials?.[0]?.password, "secret_initial_password_123");

  // Step 2: Close modal -> state MUST be completely cleared (null)
  const closeAction = { type: "CLOSE_CREDENTIALS" as const };
  const closedState = credentialModalReducer(openedState, closeAction);
  assert.strictEqual(closedState.isOpen, false);
  assert.strictEqual(closedState.credentials, null);
  assert.strictEqual(closedState.source, null);
});

test("Credential Reducer: state is null after a rotate-then-close", () => {
  // Step 1: Open modal with rotated credentials
  const rotateAction = {
    type: "OPEN_CREDENTIALS" as const,
    source: "rotate" as const,
    credentials: [
      {
        username: "device_plant_test",
        password: "rotated_fresh_password_456",
        client_id: "client_plant_test",
      },
    ],
  };
  const rotatedState = credentialModalReducer(initialCredentialModalState, rotateAction);
  assert.strictEqual(rotatedState.isOpen, true);
  assert.strictEqual(rotatedState.credentials?.[0]?.password, "rotated_fresh_password_456");

  // Step 2: Close modal -> state MUST be completely cleared (null)
  const closeAction = { type: "CLOSE_CREDENTIALS" as const };
  const afterCloseState = credentialModalReducer(rotatedState, closeAction);
  assert.strictEqual(afterCloseState.isOpen, false);
  assert.strictEqual(afterCloseState.credentials, null);
  assert.strictEqual(afterCloseState.source, null);
});

test("422 Field Error Mapper: maps Pydantic loc to dot-delimited field path", () => {
  const details: FastApiValidationErrorDetail[] = [
    {
      loc: ["body", "plant_id"],
      msg: "String should match pattern '^[a-z0-9_]{3,64}$'",
      type: "string_pattern_mismatch",
    },
    {
      loc: ["body", "areas", 0, "machines", 1, "signals", 2, "warn_max"],
      msg: "Input should be a valid number",
      type: "float_type",
    },
  ];

  const mapped = mapFastApi422Errors(details);
  assert.strictEqual(
    mapped["plant_id"],
    "String should match pattern '^[a-z0-9_]{3,64}$'"
  );
  assert.strictEqual(
    mapped["areas.0.machines.1.signals.2.warn_max"],
    "Input should be a valid number"
  );
});

test("422 Field Error Mapper: handles empty or non-array inputs safely", () => {
  assert.deepStrictEqual(mapFastApi422Errors(null), {});
  assert.deepStrictEqual(mapFastApi422Errors(undefined), {});
  assert.deepStrictEqual(mapFastApi422Errors([]), {});
});

test("Shared Fixtures: reads and validates all fixture files from filesystem", () => {
  const fixturesDir = path.resolve(process.cwd(), "../tests/fixtures/plants");
  assert.strictEqual(fs.existsSync(fixturesDir), true, "Fixtures dir must exist");

  const validMinimal = JSON.parse(
    fs.readFileSync(path.join(fixturesDir, "valid_minimal.json"), "utf-8")
  );
  assert.strictEqual(validMinimal.plant_id, "plant_minimal_fixture");
  assert.strictEqual(Array.isArray(validMinimal.areas), true);

  const invalidDup = JSON.parse(
    fs.readFileSync(path.join(fixturesDir, "invalid_duplicate_signals.json"), "utf-8")
  );
  const signals = invalidDup.areas[0].machines[0].signals;
  assert.strictEqual(signals[0].signal_code, signals[1].signal_code);

  const invalidPattern = JSON.parse(
    fs.readFileSync(path.join(fixturesDir, "invalid_pattern.json"), "utf-8")
  );
  assert.match(invalidPattern.plant_id, /[^a-z0-9_]/);

  const thresholdViolation = JSON.parse(
    fs.readFileSync(path.join(fixturesDir, "threshold_order_violation.json"), "utf-8")
  );
  const tSig = thresholdViolation.areas[0].machines[0].signals[0];
  assert.strictEqual(tSig.normal_min > tSig.normal_max, true);
});

test("Admin API: createAdminPlant sends POST with payload and Bearer header", async () => {
  let capturedUrl = "";
  let capturedHeaders: Record<string, string> = {};
  let capturedBody = "";

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    capturedUrl = url.toString();
    capturedHeaders = (init?.headers as Record<string, string>) || {};
    capturedBody = (init?.body as string) || "";
    return new Response(
      JSON.stringify({
        plant_id: "plant_test_create",
        name: "Test Plant",
        timezone: "UTC",
        has_viewer_token: false,
        device_usernames: ["device_plant_test_create"],
        areas: [],
        one_time_device_credentials: [
          {
            username: "device_plant_test_create",
            password: "generated_secret_pwd_789",
            client_id: "client_plant_test_create",
          },
        ],
        broker_reloaded: true,
      }),
      { status: 201, headers: { "Content-Type": "application/json" } }
    );
  }) as typeof globalThis.fetch;

  try {
    const payload = {
      plant_id: "plant_test_create",
      name: "Test Plant",
      timezone: "UTC",
      areas: [],
    };
    const res = await createAdminPlant("mock_admin_token_xyz", payload);

    assert.strictEqual(capturedUrl, "http://localhost:8000/api/admin/plants");
    assert.strictEqual(capturedHeaders["Authorization"], "Bearer mock_admin_token_xyz");
    assert.strictEqual(capturedHeaders["Content-Type"], "application/json");
    assert.strictEqual(JSON.parse(capturedBody).plant_id, "plant_test_create");
    assert.strictEqual(res.one_time_device_credentials?.[0]?.password, "generated_secret_pwd_789");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Admin API: rotateAdminDeviceCredentials sends POST to rotate endpoint", async () => {
  let capturedUrl = "";
  let capturedHeaders: Record<string, string> = {};

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    capturedUrl = url.toString();
    capturedHeaders = (init?.headers as Record<string, string>) || {};
    return new Response(
      JSON.stringify({
        username: "device_plant_demo_membrane",
        password: "fresh_rotated_password_999",
        client_id: "client_plant_demo_membrane",
        broker_reloaded: true,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }) as typeof globalThis.fetch;

  try {
    const res = await rotateAdminDeviceCredentials(
      "mock_admin_token_xyz",
      "plant_demo_membrane"
    );

    assert.strictEqual(
      capturedUrl,
      "http://localhost:8000/api/admin/plants/plant_demo_membrane/credentials/rotate"
    );
    assert.strictEqual(capturedHeaders["Authorization"], "Bearer mock_admin_token_xyz");
    assert.strictEqual(res.password, "fresh_rotated_password_999");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Admin API: updateAdminPlant appends ?confirm_removals=true when requested", async () => {
  let capturedUrl = "";

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request) => {
    capturedUrl = url.toString();
    return new Response(
      JSON.stringify({
        plant_id: "plant_test_update",
        name: "Updated Name",
        timezone: "UTC",
        has_viewer_token: false,
        device_usernames: [],
        areas: [],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }) as typeof globalThis.fetch;

  try {
    const payload = {
      plant_id: "plant_test_update",
      name: "Updated Name",
      timezone: "UTC",
      areas: [],
    };
    await updateAdminPlant("mock_admin_token_xyz", "plant_test_update", payload, true);
    assert.strictEqual(
      capturedUrl,
      "http://localhost:8000/api/admin/plants/plant_test_update?confirm_removals=true"
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("diffPlantRemovals: detects removed areas, machines, and signals", () => {
  const originalPlant = {
    areas: [
      {
        area_code: "area_1",
        machines: [
          {
            machine_code: "mach_1",
            signals: [{ signal_code: "sig_temp" }, { signal_code: "sig_press" }],
          },
          {
            machine_code: "mach_2",
            signals: [{ signal_code: "sig_flow" }],
          },
        ],
      },
      {
        area_code: "area_2",
        machines: [
          {
            machine_code: "mach_3",
            signals: [{ signal_code: "sig_speed" }],
          },
        ],
      },
    ],
  };

  const updatedPlant = {
    areas: [
      {
        area_code: "area_1",
        machines: [
          {
            machine_code: "mach_1",
            signals: [{ signal_code: "sig_temp" }], // sig_press removed
          },
          // mach_2 removed
        ],
      },
      // area_2 removed (and mach_3 removed)
    ],
  };

  const diff = diffPlantRemovals(originalPlant, updatedPlant);
  assert.strictEqual(diff.hasRemovals, true);
  assert.deepStrictEqual(diff.removedAreas, ["area_2"]);
  assert.deepStrictEqual(diff.removedMachines, ["mach_2", "mach_3"]);
  assert.deepStrictEqual(diff.removedSignals, [
    "mach_1:sig_press",
    "mach_2:sig_flow",
    "mach_3:sig_speed",
  ]);
});

test("409 parsing: extracts removed components from backend 409 error detail", () => {
  const detail =
    "Updating plant would remove existing components (areas: ['area_old'], machines: ['mach_old'], signals: ['mach_1:sig_press', 'mach_2:sig_flow']). Pass ?confirm_removals=true to proceed.";

  const parsed = parse409Removals(detail);
  assert.strictEqual(parsed.isRemovalConflict, true);
  assert.deepStrictEqual(parsed.removedAreas, ["area_old"]);
  assert.deepStrictEqual(parsed.removedMachines, ["mach_old"]);
  assert.deepStrictEqual(parsed.removedSignals, ["mach_1:sig_press", "mach_2:sig_flow"]);

  // Test non-removal error detail
  const nonRemoval = parse409Removals("Plant 'plant_1' already exists");
  assert.strictEqual(nonRemoval.isRemovalConflict, false);
  assert.deepStrictEqual(nonRemoval.removedAreas, []);
  assert.deepStrictEqual(nonRemoval.removedMachines, []);
  assert.deepStrictEqual(nonRemoval.removedSignals, []);
});

test("canConfirmDelete: enforces exact plant_id match and disables system plants", () => {
  // Matching ID on normal plant -> allowed
  assert.strictEqual(canConfirmDelete("plant_custom_1", "plant_custom_1", false), true);
  // Matching ID with surrounding whitespace -> trimmed and allowed
  assert.strictEqual(canConfirmDelete("plant_custom_1", "  plant_custom_1  ", false), true);

  // Mismatched ID -> rejected
  assert.strictEqual(canConfirmDelete("plant_custom_1", "plant_custom_2", false), false);
  assert.strictEqual(canConfirmDelete("plant_custom_1", "", false), false);

  // System plant -> always rejected even if input matches target
  assert.strictEqual(canConfirmDelete("plant_demo_membrane", "plant_demo_membrane", true), false);
  assert.strictEqual(isSystemPlant("plant_demo_membrane"), true);
  assert.strictEqual(isSystemPlant("plant_custom_1"), false);
});

test("PUT without a token field keeps the hash: updateAdminPlant preserves token state when omitted", async () => {
  let capturedBodyObj: Record<string, unknown> = {};

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    capturedBodyObj = JSON.parse((init?.body as string) || "{}");
    return new Response(
      JSON.stringify({
        plant_id: "plant_existing_token",
        name: "Updated Plant",
        timezone: "UTC",
        has_viewer_token: true, // Server retains hash
        device_usernames: [],
        areas: [],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }) as typeof globalThis.fetch;

  try {
    const payload = {
      plant_id: "plant_existing_token",
      name: "Updated Plant",
      timezone: "UTC",
      areas: [],
      // viewer_token is intentionally omitted
    };

    const res = await updateAdminPlant("mock_admin_token_xyz", "plant_existing_token", payload);
    assert.strictEqual(capturedBodyObj["viewer_token"], undefined);
    assert.strictEqual(res.has_viewer_token, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("deleteAdminPlant: sends DELETE request with Bearer header and returns status", async () => {
  let capturedUrl = "";
  let capturedMethod = "";
  let capturedHeaders: Record<string, string> = {};

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    capturedUrl = url.toString();
    capturedMethod = init?.method || "";
    capturedHeaders = (init?.headers as Record<string, string>) || {};
    return new Response(
      JSON.stringify({
        status: "deleted",
        plant_id: "plant_to_delete",
        broker_reloaded: true,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }) as typeof globalThis.fetch;

  try {
    const res = await deleteAdminPlant("mock_admin_token_xyz", "plant_to_delete");
    assert.strictEqual(capturedUrl, "http://localhost:8000/api/admin/plants/plant_to_delete");
    assert.strictEqual(capturedMethod, "DELETE");
    assert.strictEqual(capturedHeaders["Authorization"], "Bearer mock_admin_token_xyz");
    assert.strictEqual(res.status, "deleted");
    assert.strictEqual(res.plant_id, "plant_to_delete");
    assert.strictEqual(res.broker_reloaded, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("parsePlantJson: parses valid JSON fixture correctly", () => {
  const fixturesDir = path.resolve(process.cwd(), "../tests/fixtures/plants");
  const rawJson = fs.readFileSync(path.join(fixturesDir, "valid_minimal.json"), "utf-8");

  const result = parsePlantJson(rawJson);
  assert.strictEqual(result.success, true);
  assert.strictEqual(result.error, null);
  assert.strictEqual(result.data?.plant_id, "plant_minimal_fixture");
  assert.strictEqual(Array.isArray(result.data?.areas), true);
});

test("parsePlantJson: extracts line and column position on syntax error", () => {
  const malformedJson = `{\n  "plant_id": "bad_syntax",\n  "name": "Missing comma"\n  "areas": []\n}`;
  const result = parsePlantJson(malformedJson);
  assert.strictEqual(result.success, false);
  assert.strictEqual(result.data, null);
  assert.match(result.error || "", /line \d+|position \d+/i);
});

test("validatePlantDefinitionAdvisory: validates shared fixtures correctly", () => {
  const fixturesDir = path.resolve(process.cwd(), "../tests/fixtures/plants");

  // 1. valid_minimal -> valid
  const valid = JSON.parse(
    fs.readFileSync(path.join(fixturesDir, "valid_minimal.json"), "utf-8")
  );
  const validRes = validatePlantDefinitionAdvisory(valid);
  assert.strictEqual(validRes.valid, true);
  assert.deepStrictEqual(validRes.errors, {});

  // 2. invalid_pattern -> pattern error on plant_id
  const invPattern = JSON.parse(
    fs.readFileSync(path.join(fixturesDir, "invalid_pattern.json"), "utf-8")
  );
  const patRes = validatePlantDefinitionAdvisory(invPattern);
  assert.strictEqual(patRes.valid, false);
  assert.match(patRes.errors["plant_id"] || "", /pattern|^[a-z0-9_]{3,64}$/i);

  // 3. invalid_duplicate_signals -> error on duplicate signal
  const invDup = JSON.parse(
    fs.readFileSync(path.join(fixturesDir, "invalid_duplicate_signals.json"), "utf-8")
  );
  const dupRes = validatePlantDefinitionAdvisory(invDup);
  assert.strictEqual(dupRes.valid, false);
  assert.match(Object.values(dupRes.errors).join(" "), /duplicate|already defined/i);
});

test("Export Redaction: exported JSON raw string never contains sensitive token or password fields", () => {
  const dirtyPlant = {
    plant_id: "plant_secret_test",
    name: "Secret Plant",
    timezone: "UTC",
    viewer_token: "super_secret_token_123",
    viewer_token_hash: "hash_abcdef123456",
    password: "secret_device_password",
    password_hash: "pbkdf2_sha256$123456$hash",
    device_usernames: ["device_plant_secret_test"],
    mqtt_credentials: [
      {
        username: "device_plant_secret_test",
        password: "secret_device_password",
        password_hash: "pbkdf2_sha256$123456$hash",
      },
    ],
    areas: [
      {
        area_code: "area_1",
        name: "Area 1",
        display_order: 1,
        machines: [
          {
            machine_code: "mach_1",
            name: "Machine 1",
            machine_type: "standard",
            display_order: 1,
            signals: [
              {
                signal_code: "temp",
                name: "Temp",
                unit: "°C",
                data_type: "float",
                display_order: 1,
              },
            ],
          },
        ],
      },
    ],
  };

  const exportedRaw = exportPlantDefinitionJson(dirtyPlant);

  assert.strictEqual(typeof exportedRaw, "string");
  // Check raw string directly:
  assert.strictEqual(
    /viewer_token/i.test(exportedRaw),
    false,
    "Raw string must not contain viewer_token"
  );
  assert.strictEqual(
    /viewer_token_hash/i.test(exportedRaw),
    false,
    "Raw string must not contain viewer_token_hash"
  );
  assert.strictEqual(
    /password/i.test(exportedRaw),
    false,
    "Raw string must not contain password"
  );
  assert.strictEqual(
    /password_hash/i.test(exportedRaw),
    false,
    "Raw string must not contain password_hash"
  );
  assert.strictEqual(exportedRaw.includes("super_secret_token_123"), false);
  assert.strictEqual(exportedRaw.includes("secret_device_password"), false);

  const parsed = JSON.parse(exportedRaw);
  assert.strictEqual(parsed.plant_id, "plant_secret_test");
  assert.strictEqual(parsed.name, "Secret Plant");
  assert.strictEqual(parsed.areas.length, 1);
});


