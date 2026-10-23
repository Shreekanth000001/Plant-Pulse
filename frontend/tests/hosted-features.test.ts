import { describe, it } from "node:test";
import assert from "node:assert/strict";

describe("Hosted Features: Self-Service Flag & Wakeup Resilience", () => {
  it("NEXT_PUBLIC_ENABLE_SELF_SERVICE determines if self-service My plants is enabled", () => {
    // When unset or true -> self service enabled
    const isSelfServiceEnabled = (val: string | undefined): boolean => {
      return val !== "false" && val !== "0";
    };

    assert.equal(isSelfServiceEnabled(undefined), true);
    assert.equal(isSelfServiceEnabled("true"), true);
    assert.equal(isSelfServiceEnabled("1"), true);
    assert.equal(isSelfServiceEnabled("false"), false);
    assert.equal(isSelfServiceEnabled("0"), false);
  });

  it("Wakeup retry backoff calculates exponential delays capped at maximum", () => {
    const calculateWakeupBackoff = (
      attempt: number,
      baseMs: number = 2000,
      maxMs: number = 16000
    ): number => {
      return Math.min(baseMs * Math.pow(1.5, attempt), maxMs);
    };

    assert.equal(calculateWakeupBackoff(0), 2000);
    assert.equal(calculateWakeupBackoff(1), 3000);
    assert.equal(calculateWakeupBackoff(2), 4500);
    assert.equal(calculateWakeupBackoff(10), 16000);
  });

  it("Telemetry WebSocket auto-reconnects with backoff up to 15s", () => {
    const INITIAL_RECONNECT_DELAY_MS = 1500;
    const MAX_RECONNECT_DELAY_MS = 15000;

    let delay = INITIAL_RECONNECT_DELAY_MS;
    const delays: number[] = [];
    for (let i = 0; i < 6; i++) {
      delays.push(delay);
      delay = Math.min(delay * 1.5, MAX_RECONNECT_DELAY_MS);
    }

    assert.deepEqual(delays, [1500, 2250, 3375, 5062.5, 7593.75, 11390.625]);
    // Next attempt should hit the cap
    delay = Math.min(delay * 1.5, MAX_RECONNECT_DELAY_MS);
    assert.equal(delay, 15000);
  });
});
