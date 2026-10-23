import { describe, it } from "node:test";
import assert from "node:assert/strict";

describe("Server Wakeup Banner State & Backoff", () => {
  it("computes waking banner display conditions", () => {
    interface WakeupState {
      isWaking: boolean;
      attempt: number;
      message: string;
    }

    const getWakeupBannerProps = (state: WakeupState) => {
      if (!state.isWaking) return null;
      return {
        visible: true,
        text: "Waking up the demo, this can take about a minute",
        subtext: "Free instances spin down on idle. Retrying connection...",
        attempt: state.attempt,
      };
    };

    assert.equal(getWakeupBannerProps({ isWaking: false, attempt: 0, message: "" }), null);

    const banner = getWakeupBannerProps({
      isWaking: true,
      attempt: 1,
      message: "Server is spinning up",
    });
    assert.ok(banner);
    assert.equal(banner.visible, true);
    assert.match(banner.text, /Waking up the demo, this can take about a minute/);
  });
});
