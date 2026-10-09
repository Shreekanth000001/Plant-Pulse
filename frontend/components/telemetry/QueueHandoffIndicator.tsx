"use client";

import React from "react";

interface QueueHandoffIndicatorProps {
  fromStage: string;
  toStage: string;
  depth: number;
  isDownstreamStarved?: boolean;
}

export function QueueHandoffIndicator({
  fromStage,
  toStage,
  depth,
  isDownstreamStarved = false,
}: QueueHandoffIndicatorProps) {
  // Bottleneck status
  const isBottleneck = depth >= 8;
  const isElevated = depth >= 4 && depth < 8;

  let badgeBorder = "border-slate-800 bg-slate-900/90 text-slate-300";
  let statusText = "BUFFER NORMAL";
  let statusColor = "text-emerald-400";
  let barColor = "bg-emerald-500";

  if (isDownstreamStarved && depth === 0) {
    statusText = "DOWNSTREAM STARVED (0 WAITING)";
    statusColor = "text-amber-400";
    badgeBorder = "border-amber-600/40 bg-amber-950/40 text-amber-300";
    barColor = "bg-amber-400";
  } else if (isBottleneck) {
    statusText = "BOTTLENECK DETECTED";
    statusColor = "text-rose-400";
    badgeBorder = "border-rose-600/50 bg-rose-950/50 text-rose-300";
    barColor = "bg-rose-500 animate-pulse";
  } else if (isElevated) {
    statusText = "ELEVATED QUEUE";
    statusColor = "text-amber-400";
    badgeBorder = "border-amber-600/40 bg-amber-950/40 text-amber-300";
    barColor = "bg-amber-400";
  }

  return (
    <div className="relative my-4 py-2 px-4 rounded-lg border border-dashed border-slate-800 bg-slate-950/40 flex flex-col md:flex-row items-center justify-between gap-3">
      {/* Direction & Stage labels */}
      <div className="flex items-center gap-2 text-xs font-mono">
        <span className="font-semibold text-slate-300 uppercase">{fromStage}</span>
        <svg
          className="w-4 h-4 text-cyan-400 shrink-0 animate-pulse"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M14 5l7 7m0 0l-7 7m7-7H3"
          />
        </svg>
        <span className="font-semibold text-slate-300 uppercase">{toStage}</span>
      </div>

      {/* Queue Gauge & Visual Buffer */}
      <div className="flex items-center gap-4 w-full md:w-auto justify-end">
        {/* Visual buffer bar */}
        <div className="flex items-center gap-1.5 w-36">
          <div className="h-2 w-full bg-slate-900 rounded-full overflow-hidden border border-slate-800 flex">
            <div
              className={`h-full transition-all duration-300 ${barColor}`}
              style={{
                width: `${Math.min(100, Math.max(depth * 10, depth > 0 ? 10 : 0))}%`,
              }}
            />
          </div>
        </div>

        {/* Queue Count Pill */}
        <div
          className={`flex items-center gap-2 px-2.5 py-1 rounded border text-xs font-mono ${badgeBorder}`}
        >
          <span className="text-slate-400 uppercase text-[10px] tracking-wider">
            Queue Buffer:
          </span>
          <span className="font-bold text-sm text-cyan-400">
            {depth} {depth === 1 ? "unit" : "units"}
          </span>
          <span className="text-slate-600">•</span>
          <span className={`text-[10px] font-semibold tracking-wide ${statusColor}`}>
            {statusText}
          </span>
        </div>
      </div>
    </div>
  );
}
