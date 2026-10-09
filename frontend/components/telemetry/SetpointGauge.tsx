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
  // Anomaly severity based on standard deviations or percent drift
  const sigma = normalStd > 0 ? absDelta / normalStd : 0;

  let statusColor = "text-emerald-400";
  let badgeBg = "bg-emerald-950/60 border-emerald-500/30 text-emerald-300";
  let barColor = "bg-emerald-400";

  if (sigma > 2.5) {
    statusColor = "text-rose-400";
    badgeBg = "bg-rose-950/60 border-rose-500/40 text-rose-300";
    barColor = "bg-rose-500";
  } else if (sigma > 1.5) {
    statusColor = "text-amber-400";
    badgeBg = "bg-amber-950/60 border-amber-500/30 text-amber-300";
    barColor = "bg-amber-400";
  }

  // Calculate percentage offset for the visual deviation bar (-50% to +50% range mapped to 0-100%)
  // Range is clamp between -3 sigma to +3 sigma
  const maxSigma = 3.0;
  const clampedSigmaRatio = Math.max(-1, Math.min(1, delta / (maxSigma * normalStd)));
  // Percent from center (50%)
  const barWidthPercent = Math.abs(clampedSigmaRatio) * 50;
  const barLeftPercent = clampedSigmaRatio >= 0 ? 50 : 50 - barWidthPercent;

  return (
    <div className="bg-slate-900/70 border border-slate-800/80 rounded p-2 text-xs flex flex-col gap-1.5 transition-colors">
      <div className="flex items-center justify-between text-slate-400">
        <span className="font-medium tracking-tight uppercase text-[11px] text-slate-300 truncate">
          {label}
        </span>
        <span className="font-mono text-[10px] text-slate-500">
          SP: {setpoint.toFixed(1)}{unit}
        </span>
      </div>

      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-1">
          <span className={`font-mono text-sm font-semibold tracking-tight ${statusColor}`}>
            {actual.toFixed(2)}
          </span>
          {unit && (
            <span className="text-[10px] text-slate-500 font-mono">
              {unit}
            </span>
          )}
        </div>

        <span
          className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${badgeBg}`}
          title={`Deviation from setpoint: ${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`}
        >
          {delta >= 0 ? `+${delta.toFixed(2)}` : delta.toFixed(2)}
        </span>
      </div>

      {/* SCADA Deviation Bar Gauge */}
      <div className="relative w-full h-1.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
        {/* Center line indicator */}
        <div className="absolute left-1/2 top-0 bottom-0 w-[1px] bg-slate-600 z-10" />
        {/* Fill representing deviation */}
        <div
          className={`absolute top-0 bottom-0 ${barColor} transition-all duration-300`}
          style={{
            left: `${barLeftPercent}%`,
            width: `${barWidthPercent}%`,
          }}
        />
      </div>
    </div>
  );
}
