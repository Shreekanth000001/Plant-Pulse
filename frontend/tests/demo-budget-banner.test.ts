import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { getDemoBudgetBannerProps } from "../lib/demo-budget.ts";

describe("Demo Budget Banner", () => {
  it("renders banner message when daily demo budget is exhausted", () => {
    const activeBanner = getDemoBudgetBannerProps({
      isExhausted: true,
      remainingSeconds: 0,
      resetsAt: "2026-10-24T00:00:00Z",
    });
    assert.ok(activeBanner);
    assert.equal(activeBanner.visible, true);
    assert.equal(
      activeBanner.text,
      "Daily demo limit reached, resets at 00:00 UTC"
    );

    const hiddenBanner = getDemoBudgetBannerProps({
      isExhausted: false,
      remainingSeconds: 1200,
      resetsAt: "2026-10-24T00:00:00Z",
    });
    assert.equal(hiddenBanner, null);
  });

  it("shows demo video link when NEXT_PUBLIC_DEMO_VIDEO_URL is provided", () => {
    const bannerWithVideo = getDemoBudgetBannerProps(
      {
        isExhausted: true,
        remainingSeconds: 0,
      },
      "https://example.com/demo-video"
    );
    assert.ok(bannerWithVideo);
    assert.equal(bannerWithVideo.visible, true);
    assert.equal(bannerWithVideo.videoUrl, "https://example.com/demo-video");

    const bannerWithoutVideo = getDemoBudgetBannerProps({
      isExhausted: true,
      remainingSeconds: 0,
    });
    assert.ok(bannerWithoutVideo);
    assert.equal(bannerWithoutVideo.videoUrl, undefined);
  });
});
