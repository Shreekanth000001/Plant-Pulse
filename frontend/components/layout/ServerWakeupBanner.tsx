"use client";

import React from "react";
import { useFactoryWebSocket } from "../../context/WebSocketContext";

export function ServerWakeupBanner() {
  const { isServerWaking, wakeupAttempt, retryInitialFetch } = useFactoryWebSocket();

  if (!isServerWaking) {
    return null;
  }

  return (
    <div className="w-full bg-amber-500/10 border-b border-amber-500/30 px-4 py-2.5 text-amber-900 transition-all duration-300">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3 text-xs sm:text-sm font-sans">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500" />
          </span>
          <p className="font-medium text-amber-950">
            <span className="font-semibold">Waking up the demo, this can take about a minute.</span>
            {wakeupAttempt > 0 && (
              <span className="ml-1.5 text-amber-800/80 font-mono text-xs">
                (Attempt #{wakeupAttempt})
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => retryInitialFetch()}
            className="px-2.5 py-1 text-xs font-semibold rounded-md bg-amber-500 text-white hover:bg-amber-600 active:bg-amber-700 transition-colors shadow-xs cursor-pointer"
          >
            Retry Now
          </button>
        </div>
      </div>
    </div>
  );
}
