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
