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

  let badgeBorder = "border-slate-200 bg-slate-50 text-slate-700";
  let statusText = "Buffer Normal";
  let statusColor = "text-emerald-700";
  let barGradient = "from-emerald-500 to-teal-500";

  if (isDownstreamStarved && depth === 0) {
    statusText = "Downstream Starved (0 waiting)";
    statusColor = "text-amber-800";
    badgeBorder = "border-amber-200 bg-amber-50 text-amber-900";
    barGradient = "from-amber-400 to-orange-500";
  } else if (isBottleneck) {
    statusText = "Bottleneck Detected";
    statusColor = "text-rose-700";
    badgeBorder = "border-rose-200 bg-rose-50 text-rose-900";
    barGradient = "from-rose-500 to-rose-600 animate-pulse";
  } else if (isElevated) {
    statusText = "Elevated Queue";
    statusColor = "text-amber-800";
    badgeBorder = "border-amber-200 bg-amber-50 text-amber-900";
    barGradient = "from-amber-400 to-yellow-500";
  }

  return (
    <div className="relative my-4 py-3 px-5 rounded-2xl border border-slate-200 bg-white flex flex-col md:flex-row items-center justify-between gap-3 shadow-xs hover:border-slate-300 transition-all duration-200">
      {/* Direction & Stage labels */}
      <div className="flex items-center gap-3 text-xs">
        <span className="font-bold text-slate-900">{fromStage}</span>
        <div className="flex items-center gap-1 text-blue-600">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />
          <svg
            className="w-4 h-4 shrink-0"
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
        </div>
        <span className="font-bold text-slate-900">{toStage}</span>
      </div>

      {/* Queue Gauge & Visual Buffer */}
      <div className="flex items-center gap-4 w-full md:w-auto justify-end">
        {/* Visual buffer bar */}
        <div className="flex items-center gap-2 w-32 sm:w-40">
          <div className="h-2 w-full bg-slate-200 rounded-full overflow-hidden border border-slate-100 flex">
            <div
              className={`h-full bg-gradient-to-r ${barGradient} rounded-full transition-all duration-300`}
              style={{
                width: `${Math.min(100, Math.max(depth * 10, depth > 0 ? 10 : 0))}%`,
              }}
            />
          </div>
        </div>

        {/* Queue Count Pill */}
        <div
          className={`flex items-center gap-2.5 px-3 py-1.5 rounded-xl border text-xs font-medium shadow-2xs ${badgeBorder}`}
        >
          <span className="text-slate-500 text-xs">
            Transfer Buffer:
          </span>
          <span className="font-bold text-sm text-slate-900 font-mono">
            {depth} {depth === 1 ? "unit" : "units"}
          </span>
          <span className="text-slate-300">•</span>
          <span className={`text-xs font-semibold ${statusColor}`}>
            {statusText}
          </span>
        </div>
      </div>
    </div>
  );
}
