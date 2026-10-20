import test from "node:test";
import assert from "node:assert/strict";
import { insertTimeGaps, buildHistoryQueryParams } from "../lib/plant-utils.ts";

test("insertTimeGaps: returns empty array when input is empty", () => {
  const result = insertTimeGaps([], 60);
  assert.deepEqual(result, []);
});

test("insertTimeGaps: returns same array when data is contiguous without gaps", () => {
  const contiguous = [
    { timestamp: "2026-10-20T19:00:00Z", avg: 50.0, min: 48.0, max: 52.0, count: 5 },
    { timestamp: "2026-10-20T19:01:00Z", avg: 51.0, min: 49.0, max: 53.0, count: 5 },
    { timestamp: "2026-10-20T19:02:00Z", avg: 52.0, min: 50.0, max: 54.0, count: 5 },
  ];
  const result = insertTimeGaps(contiguous, 60);
  assert.equal(result.length, 3);
  assert.equal(result[0].avg, 50.0);
  assert.equal(result[1].avg, 51.0);
  assert.equal(result[2].avg, 52.0);
});

test("insertTimeGaps: inserts null sentinel gap point when missing interval exceeds threshold", () => {
  const withGap = [
    { timestamp: "2026-10-20T19:00:00Z", avg: 50.0, min: 48.0, max: 52.0, count: 5 },
    // 5-minute gap between 19:00 and 19:05 (bucket size = 60s, threshold = 90s)
    { timestamp: "2026-10-20T19:05:00Z", avg: 55.0, min: 53.0, max: 57.0, count: 5 },
  ];
  const result = insertTimeGaps(withGap, 60);
  assert.equal(result.length, 3);
  assert.equal(result[0].avg, 50.0);
  // Gap sentinel point inserted in-between with null values
  assert.equal(result[1].avg, null);
  assert.equal(result[1].min, null);
  assert.equal(result[1].max, null);
  assert.equal(result[2].avg, 55.0);
});

test("buildHistoryQueryParams: default is 1h and 300 points", () => {
  const fixedNow = new Date("2026-10-20T20:00:00Z");
  const params = buildHistoryQueryParams({ now: fixedNow });
  assert.equal(params.points, 300);
  assert.equal(params.end, "2026-10-20T20:00:00Z");
  assert.equal(params.start, "2026-10-20T19:00:00Z");
});

test("buildHistoryQueryParams: clamps points between 10 and 500", () => {
  const low = buildHistoryQueryParams({ points: 2 });
  assert.equal(low.points, 10);

  const high = buildHistoryQueryParams({ points: 999 });
  assert.equal(high.points, 500);
});

test("fetchSignalHistory: sends Authorization Bearer header and query params", async () => {
  const { fetchSignalHistory } = await import("../lib/api.ts");
  const originalFetch = globalThis.fetch;
  let capturedUrl = "";
  let capturedHeaders: Record<string, string> = {};

  try {
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      return new Response(
        JSON.stringify({
          plant_id: "plant_demo_membrane",
          machine_code: "press_01",
          signal_code: "hydraulic_pressure",
          start: "2026-10-20T19:00:00Z",
          end: "2026-10-20T20:00:00Z",
          bucket_sec: 13,
          total_points: 1,
          data: [{ bucket_start: "2026-10-20T19:00:00Z", count: 1, avg: 45.2, min: 45.2, max: 45.2, last: 45.2 }],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const res = await fetchSignalHistory(
      "plant_demo_membrane",
      "press_01",
      "hydraulic_pressure",
      { start: "2026-10-20T19:00:00Z", end: "2026-10-20T20:00:00Z", points: 300 },
      "test_token_123"
    );

    assert.equal(res.total_points, 1);
    assert.equal(capturedHeaders["Authorization"], "Bearer test_token_123");
    assert.ok(capturedUrl.includes("/api/plants/plant_demo_membrane/machines/press_01/signals/hydraulic_pressure/history"));
    assert.ok(capturedUrl.includes("points=300"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

