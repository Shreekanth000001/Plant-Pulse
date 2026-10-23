"use client";

import React, { useEffect, useState } from "react";
import {
  DemoBudgetState,
  getDemoBudgetBannerProps,
} from "../../lib/demo-budget";

export function DemoBudgetBanner() {
  const [budget, setBudget] = useState<DemoBudgetState>({
    isExhausted: false,
    remainingSeconds: null,
  });

  useEffect(() => {
    let mounted = true;

    async function checkBudget() {
      try {
        const res = await fetch("/api/demo-budget", { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          if (mounted) {
            setBudget({
              isExhausted: Boolean(data.exhausted),
              remainingSeconds: data.remaining_seconds ?? null,
              resetsAt: data.resets_at,
            });
          }
        }
      } catch {
        // Fail open if budget check fails
      }
    }

    checkBudget();
    const interval = setInterval(checkBudget, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const videoUrl = process.env.NEXT_PUBLIC_DEMO_VIDEO_URL;
  const bannerProps = getDemoBudgetBannerProps(budget, videoUrl);
  if (!bannerProps) {
    return null;
  }

  return (
    <div
      role="alert"
      className="w-full bg-rose-500/10 border-b border-rose-500/30 px-4 py-2.5 text-rose-900 transition-all duration-300"
    >
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3 text-xs sm:text-sm font-sans">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-rose-500" />
          </span>
          <p className="font-medium text-rose-950">
            <span className="font-semibold">{bannerProps.text}</span>
            <span className="ml-1.5 text-rose-800/80 text-xs">
              Simulator heartbeat paused to stay within free hosting limits.
            </span>
          </p>
        </div>
        {bannerProps.videoUrl && (
          <div className="flex items-center gap-2">
            <a
              href={bannerProps.videoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-md bg-rose-600 text-white hover:bg-rose-700 active:bg-rose-800 transition-colors shadow-xs"
            >
              Watch demo video
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
