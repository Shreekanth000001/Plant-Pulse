"use client";

import React from "react";

interface SetpointGaugeProps {
  label: string;
  actual: number;
  setpoint: number;
  unit?: string;
  normalStd?: number;
}

export function SetpointGauge({
  label,
  actual,
  setpoint,
  unit = "",
  normalStd = 1.5,
}: SetpointGaugeProps) {
  const delta = actual - setpoint;
  const absDelta = Math.abs(delta);
  const sigma = normalStd > 0 ? absDelta / normalStd : 0;

  let statusColor = "text-emerald-700";
  let badgeBg = "bg-emerald-50 border-emerald-200 text-emerald-700";
  let barColor = "bg-gradient-to-r from-emerald-500 to-teal-500";

  if (sigma > 2.5) {
    statusColor = "text-rose-700";
    badgeBg = "bg-rose-50 border-rose-200 text-rose-700";
    barColor = "bg-rose-500";
  } else if (sigma > 1.5) {
    statusColor = "text-amber-800";
    badgeBg = "bg-amber-50 border-amber-200 text-amber-800";
    barColor = "bg-amber-400";
  }

  // Calculate percentage offset for the visual deviation bar (-50% to +50% mapped to 0-100%)
  const maxSigma = 3.0;
  const clampedSigmaRatio = Math.max(-1, Math.min(1, delta / (maxSigma * normalStd)));
  const barWidthPercent = Math.abs(clampedSigmaRatio) * 50;
  const barLeftPercent = clampedSigmaRatio >= 0 ? 50 : 50 - barWidthPercent;

  return (
    <div className="bg-slate-50 border border-slate-200/90 rounded-xl p-2.5 text-xs flex flex-col gap-2 transition-all hover:border-slate-300 shadow-2xs">
      <div className="flex items-center justify-between text-slate-500">
        <span className="font-semibold text-[11px] text-slate-800 truncate">
          {label}
        </span>
        <span className="text-[10px] text-slate-500 font-mono">
          Target: {setpoint.toFixed(1)}{unit}
        </span>
      </div>

      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-1">
          <span className={`font-mono text-sm font-bold tracking-tight ${statusColor}`}>
            {actual.toFixed(2)}
          </span>
          {unit && (
            <span className="text-[10px] text-slate-500 font-sans">
              {unit}
            </span>
          )}
        </div>

        <span
          className={`font-mono text-[10px] px-2 py-0.5 rounded-full border font-semibold ${badgeBg}`}
          title={`Deviation from setpoint: ${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`}
        >
          {delta >= 0 ? `+${delta.toFixed(2)}` : delta.toFixed(2)}
        </span>
      </div>

      {/* Modern Center-Aligned Deviation Track with Accessibility */}
      <div
        role="meter"
        aria-label={`${label} deviation`}
        aria-valuenow={actual}
        aria-valuemin={Number((setpoint - 3 * normalStd).toFixed(1))}
        aria-valuemax={Number((setpoint + 3 * normalStd).toFixed(1))}
        className="relative w-full h-1.5 bg-slate-200 rounded-full overflow-hidden border border-slate-100"
      >
        {/* Center line indicator */}
        <div className="absolute left-1/2 top-0 bottom-0 w-[1px] bg-slate-400 z-10" />
        {/* Fill representing deviation */}
        <div
          className={`absolute top-0 bottom-0 ${barColor} rounded-full transition-all duration-300`}
          style={{
            left: `${barLeftPercent}%`,
            width: `${barWidthPercent}%`,
          }}
        />
      </div>
    </div>
  );
}
