import test from "node:test";
import assert from "node:assert/strict";

import {
  AdminApiError,
  checkAdminHealth,
  fetchAdminPlants,
  fetchAdminPlantDetail,
  formatAdminErrorMessage,
} from "../lib/admin-api.ts";

test("Admin API: Bearer header attached to request", async () => {
  const originalFetch = globalThis.fetch;
  let capturedHeaders: Record<string, string> = {};

  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      return new Response(
        JSON.stringify([
          {
            plant_id: "plant_alpha",
            name: "Alpha Plant",
            timezone: "UTC",
            has_viewer_token: false,
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const token = "test_admin_secret_token_1234567890_32char";
    const plants = await fetchAdminPlants(token);
    assert.equal(plants.length, 1);
    assert.equal(plants[0].plant_id, "plant_alpha");
    assert.equal(capturedHeaders["Authorization"], `Bearer ${token}`);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Admin API: 401 response throws typed AdminApiError with status 401", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Missing or invalid Bearer token" }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    await assert.rejects(
      async () => {
        await fetchAdminPlants("invalid_token");
      },
      (err: unknown) => {
        assert(err instanceof AdminApiError, "Error must be instance of AdminApiError");
        assert.equal(err.status, 401);
        assert.equal(err.isUnauthorized, true);
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Admin API: 429 response parses Retry-After header and sets retryAfterSeconds", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Too many failed authentication attempts. Locked out." }),
        {
          status: 429,
          headers: {
            "Content-Type": "application/json",
            "Retry-After": "45",
          },
        }
      );
    }) as typeof fetch;

    await assert.rejects(
      async () => {
        await fetchAdminPlantDetail("plant_alpha", "wrong_token");
      },
      (err: unknown) => {
        assert(err instanceof AdminApiError, "Error must be instance of AdminApiError");
        assert.equal(err.status, 429);
        assert.equal(err.retryAfter, 45);
        assert.equal(err.isThrottled, true);
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Admin API: 503 vs network failure produces distinct error messages", async () => {
  const originalFetch = globalThis.fetch;
  try {
    // 1. Server 503 (ADMIN_TOKEN not configured)
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          detail: "Admin API disabled: ADMIN_TOKEN environment variable is not configured",
        }),
        { status: 503, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    let serverErr: unknown;
    try {
      await checkAdminHealth("valid_token");
    } catch (err) {
      serverErr = err;
    }
    assert(serverErr instanceof AdminApiError);
    assert.equal(serverErr.status, 503);
    const serverMsg = formatAdminErrorMessage(serverErr);
    assert.match(serverMsg, /ADMIN_TOKEN.*not configured/i);

    // 2. Network failure (fetch throws TypeError / Connection refused)
    globalThis.fetch = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;

    let netErr: unknown;
    try {
      await checkAdminHealth("valid_token");
    } catch (err) {
      netErr = err;
    }
    assert(netErr instanceof AdminApiError);
    assert.equal(netErr.status, 0); // 0 indicates network/transport failure
    const netMsg = formatAdminErrorMessage(netErr);
    assert.match(netMsg, /network failure|cannot connect|offline/i);
    assert.notEqual(netMsg, serverMsg);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Admin API: token never appears in formatted error string or message", () => {
  const secretToken = "super_secret_admin_token_do_not_leak_9999";
  const err = new AdminApiError(
    `Failed request to http://localhost:8000/api/admin/plants with token Bearer ${secretToken}`,
    401,
    undefined,
    secretToken
  );

  const formatted = formatAdminErrorMessage(err);
  assert.equal(formatted.includes(secretToken), false, "Raw token must not appear in formatted message");
  assert.equal(err.message.includes(secretToken), false, "Raw token must be scrubbed from Error.message");
  assert.match(formatted, /unauthorized|invalid admin token/i);
});
