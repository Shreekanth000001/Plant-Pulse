import test from "node:test";
import assert from "node:assert/strict";

import {
  fetchPlantDefinition,
  fetchPlantMachinesLatest,
  fetchRecentUnits,
  fetchUnitHistory,
  createWsTicket,
  getWsUrl,
  getApiBaseUrl,
  ApiError,
} from "../lib/api.ts";
import {
  safeSessionStorageGet,
  safeSessionStorageSet,
  safeSessionStorageRemove,
} from "../lib/plant-utils.ts";

test("Viewer Auth: fetchPlantDefinition sends Authorization Bearer header when token provided", async () => {
  const originalFetch = globalThis.fetch;
  let capturedHeaders: Record<string, string> = {};

  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      return new Response(
        JSON.stringify({
          plant_id: "plant_water_district_9",
          name: "District 9 Water Station",
          timezone: "America/New_York",
          has_viewer_token: true,
          areas: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const def = await fetchPlantDefinition(
      "plant_water_district_9",
      "district9_secret_xyz"
    );
    assert.equal(def.plant_id, "plant_water_district_9");
    assert.equal(
      capturedHeaders["Authorization"],
      "Bearer district9_secret_xyz"
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Viewer Auth: fetchPlantDefinition throws ApiError(401) on 401 response", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await assert.rejects(
      async () => {
        await fetchPlantDefinition("plant_water_district_9", "invalid_token");
      },
      (err: unknown) => {
        assert(err instanceof ApiError);
        assert.equal(err.status, 401);
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Viewer Auth: fetchPlantMachinesLatest sends Authorization Bearer header when token provided", async () => {
  const originalFetch = globalThis.fetch;
  let capturedHeaders: Record<string, string> = {};

  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      return new Response(
        JSON.stringify([
          {
            machine_code: "pump_01",
            area_code: "pump_house",
            name: "Primary Feed Pump 1",
            machine_type: "centrifugal_pump",
            state: "RUNNING",
            sub_state: null,
            last_seen_at: null,
            signals: {},
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const machines = await fetchPlantMachinesLatest(
      "plant_water_district_9",
      "district9_secret_xyz"
    );
    assert.equal(machines.length, 1);
    assert.equal(machines[0].machine_code, "pump_01");
    assert.equal(
      capturedHeaders["Authorization"],
      "Bearer district9_secret_xyz"
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Viewer Auth: createWsTicket issues single-use ticket with Bearer token", async () => {
  const originalFetch = globalThis.fetch;
  let capturedMethod = "";
  let capturedHeaders: Record<string, string> = {};

  try {
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedMethod = init?.method || "";
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      const url = String(input);
      assert(url.includes("/api/plants/plant_water_district_9/ws-ticket"));

      return new Response(
        JSON.stringify({
          ticket: "ticket_mock_abc_123",
          expires_in: 30,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const res = await createWsTicket(
      "plant_water_district_9",
      "district9_secret_xyz"
    );
    assert.equal(capturedMethod, "POST");
    assert.equal(
      capturedHeaders["Authorization"],
      "Bearer district9_secret_xyz"
    );
    assert.equal(res.ticket, "ticket_mock_abc_123");
    assert.equal(res.expires_in, 30);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Viewer Auth: getWsUrl appends ticket parameter when provided", () => {
  const urlWithTicket = getWsUrl("plant_water_district_9", "ticket_abc_123");
  assert.equal(
    urlWithTicket,
    "ws://localhost:8000/ws/plant_water_district_9/telemetry?ticket=ticket_abc_123"
  );

  const urlWithoutTicket = getWsUrl("plant_demo_membrane");
  assert.equal(
    urlWithoutTicket,
    "ws://localhost:8000/ws/plant_demo_membrane/telemetry"
  );
});

test("Viewer Auth: safeSessionStorage wrappers handle storage safely", () => {
  const mockStorage: Record<string, string> = {};
  const fakeSessionStorage = {
    getItem: (key: string) => mockStorage[key] ?? null,
    setItem: (key: string, val: string) => {
      mockStorage[key] = val;
    },
    removeItem: (key: string) => {
      delete mockStorage[key];
    },
  } as Storage;

  assert.equal(
    safeSessionStorageGet("test_key", "default_val", fakeSessionStorage),
    "default_val"
  );

  safeSessionStorageSet("test_key", "secret_token_123", fakeSessionStorage);
  assert.equal(
    safeSessionStorageGet("test_key", "default_val", fakeSessionStorage),
    "secret_token_123"
  );

  safeSessionStorageRemove("test_key", fakeSessionStorage);
  assert.equal(
    safeSessionStorageGet("test_key", "default_val", fakeSessionStorage),
    "default_val"
  );

  // Fallback when throwing
  const throwingStorage = {
    getItem: () => {
      throw new Error("Quota/Security error");
    },
    setItem: () => {
      throw new Error("Quota/Security error");
    },
    removeItem: () => {
      throw new Error("Quota/Security error");
    },
  } as unknown as Storage;

  assert.equal(
    safeSessionStorageGet("any_key", "fallback", throwingStorage),
    "fallback"
  );
  assert.doesNotThrow(() => {
    safeSessionStorageSet("any_key", "val", throwingStorage);
    safeSessionStorageRemove("any_key", throwingStorage);
  });
});

test("Viewer Auth: Reconnects generate fresh ticket and never reuse consumed ticket", async () => {
  const originalFetch = globalThis.fetch;
  let ticketCounter = 0;

  try {
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/ws-ticket")) {
        ticketCounter++;
        return new Response(
          JSON.stringify({
            ticket: `ticket_fresh_${ticketCounter}`,
            expires_in: 30,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("{}", { status: 200 });
    }) as typeof fetch;

    // Simulate initial connection
    const t1 = await createWsTicket("plant_water_district_9", "token_123");
    const wsUrl1 = getWsUrl("plant_water_district_9", t1.ticket);
    assert.equal(t1.ticket, "ticket_fresh_1");
    assert(wsUrl1.includes("ticket=ticket_fresh_1"));

    // Simulate reconnect after drop -> MUST request fresh ticket
    const t2 = await createWsTicket("plant_water_district_9", "token_123");
    const wsUrl2 = getWsUrl("plant_water_district_9", t2.ticket);
    assert.equal(t2.ticket, "ticket_fresh_2");
    assert(wsUrl2.includes("ticket=ticket_fresh_2"));
    assert.notEqual(wsUrl1, wsUrl2, "Must not reuse ticket across reconnects");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("WebSocket and API URL: derives host and protocol from window.location when env vars are unset and preserves overrides", () => {
  const originalEnvApi = process.env.NEXT_PUBLIC_API_URL;
  const originalEnvWs = process.env.NEXT_PUBLIC_WS_URL;
  type GlobalWithWindow = typeof globalThis & {
    window?: { location: { hostname: string; protocol: string } };
  };
  const target = globalThis as GlobalWithWindow;
  const originalWindow = target.window;

  try {
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_WS_URL;

    // 1. Simulate http on a custom hostname
    target.window = {
      location: {
        hostname: "192.168.1.100",
        protocol: "http:",
      },
    };

    assert.equal(getApiBaseUrl(), "http://192.168.1.100:8000");
    assert.equal(
      getWsUrl("plant_demo_membrane"),
      "ws://192.168.1.100:8000/ws/plant_demo_membrane/telemetry"
    );

    // 2. Simulate https on another domain
    target.window = {
      location: {
        hostname: "plantpulse.internal",
        protocol: "https:",
      },
    };

    assert.equal(getApiBaseUrl(), "https://plantpulse.internal:8000");
    assert.equal(
      getWsUrl("plant_water_district_9", "ticket_sec_1"),
      "wss://plantpulse.internal:8000/ws/plant_water_district_9/telemetry?ticket=ticket_sec_1"
    );

    // 3. Env overrides take precedence over window.location
    process.env.NEXT_PUBLIC_API_URL = "http://override-api:9000";
    process.env.NEXT_PUBLIC_WS_URL = "ws://override-ws:9000";

    assert.equal(getApiBaseUrl(), "http://override-api:9000");
    assert.equal(
      getWsUrl("plant_demo_membrane"),
      "ws://override-ws:9000/ws/plant_demo_membrane/telemetry"
    );
  } finally {
    if (originalEnvApi !== undefined) {
      process.env.NEXT_PUBLIC_API_URL = originalEnvApi;
    } else {
      delete process.env.NEXT_PUBLIC_API_URL;
    }
    if (originalEnvWs !== undefined) {
      process.env.NEXT_PUBLIC_WS_URL = originalEnvWs;
    } else {
      delete process.env.NEXT_PUBLIC_WS_URL;
    }
    target.window = originalWindow;
  }
});

test("Viewer Auth: fetchRecentUnits sends Authorization Bearer header to plant-scoped route", async () => {
  const originalFetch = globalThis.fetch;
  let capturedUrl = "";
  let capturedHeaders: Record<string, string> = {};

  try {
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      return new Response(
        JSON.stringify([
          {
            unit_id: "unit_water_001",
            status: "in_progress",
            created_at: new Date().toISOString(),
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const units = await fetchRecentUnits(
      "plant_water_district_9",
      25,
      "district9_secret_xyz"
    );
    assert.equal(units.length, 1);
    assert.equal(units[0].unit_id, "unit_water_001");
    assert(capturedUrl.includes("/api/plants/plant_water_district_9/units?limit=25"));
    assert.equal(
      capturedHeaders["Authorization"],
      "Bearer district9_secret_xyz"
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Viewer Auth: fetchRecentUnits throws ApiError(401) on 401 response", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await assert.rejects(
      async () => {
        await fetchRecentUnits("plant_water_district_9", 20);
      },
      (err: unknown) => {
        assert(err instanceof ApiError);
        assert.equal(err.status, 401);
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Viewer Auth: fetchUnitHistory sends Authorization Bearer header to plant-scoped route", async () => {
  const originalFetch = globalThis.fetch;
  let capturedUrl = "";
  let capturedHeaders: Record<string, string> = {};

  try {
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      return new Response(
        JSON.stringify({
          unit_id: "unit_water_001",
          status: "in_progress",
          created_at: new Date().toISOString(),
          stages: [],
          qc_result: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const history = await fetchUnitHistory(
      "plant_water_district_9",
      "unit_water_001",
      "district9_secret_xyz"
    );
    assert.equal(history.unit_id, "unit_water_001");
    assert(capturedUrl.includes("/api/plants/plant_water_district_9/units/unit_water_001"));
    assert.equal(
      capturedHeaders["Authorization"],
      "Bearer district9_secret_xyz"
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Viewer Auth: fetchUnitHistory throws ApiError(401) on 401 response", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await assert.rejects(
      async () => {
        await fetchUnitHistory("plant_water_district_9", "unit_water_001");
      },
      (err: unknown) => {
        assert(err instanceof ApiError);
        assert.equal(err.status, 401);
        return true;
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Viewer Auth: Shareable direct link builds valid 1-click URL with encoded query params", () => {
  const origin = "https://plantpulse.example.com";
  const plantId = "plant_citrus_grove_juice";
  const token = "viewer_abc-123+xyz==";

  const shareableUrl = `${origin}/?plant=${encodeURIComponent(plantId)}&token=${encodeURIComponent(token)}`;
  assert.equal(
    shareableUrl,
    "https://plantpulse.example.com/?plant=plant_citrus_grove_juice&token=viewer_abc-123%2Bxyz%3D%3D"
  );

  const url = new URL(shareableUrl);
  assert.equal(url.searchParams.get("plant"), "plant_citrus_grove_juice");
  assert.equal(url.searchParams.get("token"), "viewer_abc-123+xyz==");
});

test("Viewer Auth: Query param token can be safely saved to sessionStorage and retrieved", () => {
  const mockStorage: Record<string, string> = {};
  const storageShim = {
    getItem: (key: string) => mockStorage[key] ?? null,
    setItem: (key: string, val: string) => {
      mockStorage[key] = val;
    },
    removeItem: (key: string) => {
      delete mockStorage[key];
    },
    clear: () => {
      for (const k of Object.keys(mockStorage)) delete mockStorage[k];
    },
    length: 0,
    key: () => null,
  } as unknown as Storage;

  const url = new URL("https://app.plantpulse.io/?plant=plant_solar_pack&token=viewer_987654321");
  const urlPlant = url.searchParams.get("plant");
  const urlToken = url.searchParams.get("token");

  assert.equal(urlPlant, "plant_solar_pack");
  assert.equal(urlToken, "viewer_987654321");

  if (urlPlant && urlToken) {
    safeSessionStorageSet(`plantpulse_viewer_token_${urlPlant}`, urlToken, storageShim);
  }

  const retrieved = safeSessionStorageGet<string | null>(
    "plantpulse_viewer_token_plant_solar_pack",
    null,
    storageShim
  );
  assert.equal(retrieved, "viewer_987654321");
});


