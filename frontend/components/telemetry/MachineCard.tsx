"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import type { MachineStatus, MachineDefinition } from "../../types/factory";
import { ReadingsGrid } from "./ReadingsGrid";

interface MachineCardProps {
  machine: MachineStatus;
  machineDef?: MachineDefinition;
  onInspect?: () => void;
}

export function MachineCard({ machine, machineDef, onInspect }: MachineCardProps) {
  const displayName = machine.name || machine.machine_id;

  // Determine state color theme
  const state = machine.machine_state?.toUpperCase() || "OFFLINE";
  const isStarved = machine.starved;

  let stateBorder = "border-slate-200";
  let stateBadgeBg = "bg-slate-100 text-slate-600 font-medium";
  let dotColor = "bg-slate-400";
  let accentBarGradient = "from-slate-300 to-slate-400";
  let panelHighlight = "";

  if (state === "FAULT") {
    stateBorder = "border-rose-200";
    stateBadgeBg = "bg-rose-50 text-rose-700 font-semibold";
    dotColor = "bg-rose-500 animate-ping";
    panelHighlight = "shadow-sm border-rose-300 ring-1 ring-rose-200";
    accentBarGradient = "from-rose-500 to-rose-600";
  } else if (state === "RUNNING") {
    stateBorder = "border-emerald-200";
    stateBadgeBg = "bg-emerald-50 text-emerald-700 font-semibold";
    dotColor = "bg-emerald-500";
    accentBarGradient = "from-emerald-500 to-teal-500";
  } else if (state === "TESTING") {
    stateBorder = "border-blue-200";
    stateBadgeBg = "bg-blue-50 text-blue-700 font-semibold";
    dotColor = "bg-blue-600 animate-pulse";
    accentBarGradient = "from-blue-600 to-indigo-600";
  } else if (state === "IDLE") {
    stateBorder = "border-amber-200";
    stateBadgeBg = "bg-amber-50 text-amber-800 font-semibold";
    dotColor = "bg-amber-400";
    accentBarGradient = "from-amber-400 to-amber-500";
  } else if (isStarved) {
    stateBadgeBg = "bg-amber-50 text-amber-800 border-amber-200 font-semibold";
    accentBarGradient = "from-amber-400 to-amber-500 animate-pulse";
  } else {
    stateBorder = "border-slate-200";
    stateBadgeBg = "bg-slate-100 text-slate-600 font-medium";
    dotColor = "bg-slate-400";
    accentBarGradient = "from-slate-300 to-slate-400";
  }

  // Vibration thresholds
  const vibration = machine.vibration ?? null;
  const vibrationFaultThreshold = 7.0;
  const isVibrationHigh = vibration !== null && vibration > 4.5;
  const isVibrationFault = vibration !== null && vibration >= vibrationFaultThreshold;

  // Unit link
  const currentUnit = machine.current_unit_id;

  // Total production and reject rate
  const good = machine.good_count ?? 0;
  const reject = machine.reject_count ?? 0;
  const totalProduced = good + reject;
  const rejectRate = totalProduced > 0 ? ((reject / totalProduced) * 100).toFixed(1) : "0.0";

  const effectiveReadings = useMemo(() => {
    const res: Record<string, number | string | boolean | null> = { ...(machine.extra || {}) };
    if (machine.signals) {
      for (const [code, sig] of Object.entries(machine.signals)) {
        if (res[code] === undefined && sig && sig.value !== undefined) {
          res[code] = sig.value;
        }
      }
    }
    return res;
  }, [machine.extra, machine.signals]);

  return (
    <div
      className={`bg-white border border-slate-200/90 rounded-2xl p-4.5 flex flex-col justify-between transition-all duration-200 hover:border-slate-300 hover:-translate-y-0.5 hover:shadow-md relative overflow-hidden shadow-xs group ${panelHighlight}`}
    >
      {/* Top Status Gradient Accent Bar */}
      <div className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${accentBarGradient}`} />

      {/* Header: ID Pill, Station Name, Status Pill */}
      <div className="flex items-start justify-between gap-2 pb-3 border-b border-slate-100 pt-1">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] font-bold text-slate-700 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-lg tracking-wider">
              {machine.machine_id.toUpperCase()}
            </span>
            <h3 className="text-sm font-semibold text-slate-900 tracking-tight truncate max-w-[170px]">
              {displayName}
            </h3>
          </div>

          {/* Phase and starved chips */}
          <div className="flex items-center gap-1.5 mt-1.5">
            {machine.phase && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 border border-slate-200">
                Phase: <span className="font-semibold text-slate-900 capitalize">{machine.phase.toLowerCase()}</span>
              </span>
            )}
            {isStarved && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-md bg-amber-50 text-amber-800 border border-amber-200 flex items-center gap-1.5 animate-pulse font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                Starved
              </span>
            )}
          </div>
        </div>

        {/* State Pill */}
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold ${stateBadgeBg} ${stateBorder}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
          <span className="capitalize">{state.toLowerCase()}</span>
        </div>
      </div>

      {/* Primary Telemetry Metrics Row */}
      <div className="grid grid-cols-2 gap-2 my-3 py-2.5 px-3 bg-slate-50 rounded-xl border border-slate-100">
        {/* Active Unit */}
        <div>
          <div className="text-[11px] text-slate-500 font-semibold">
            Active Unit
          </div>
          {currentUnit ? (
            <Link
              href={`/units/${encodeURIComponent(currentUnit)}`}
              className="inline-flex items-center gap-1 font-mono tabular-nums text-xs font-bold text-blue-600 hover:text-blue-800 hover:underline mt-1 transition-colors truncate max-w-full"
            >
              <span className="truncate">{currentUnit}</span>
              <svg className="w-3 h-3 opacity-80 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </Link>
          ) : (
            <div className="text-xs text-slate-400 mt-1 italic font-sans">
              Awaiting unit
            </div>
          )}
        </div>

        {/* Vibration / Motor Health */}
        {vibration !== null ? (
          <div>
            <div className="flex items-center justify-between text-[11px] text-slate-500 font-semibold">
              <span>Vibration</span>
              <span className={`font-mono tabular-nums text-xs font-bold ${isVibrationFault ? "text-rose-600" : isVibrationHigh ? "text-amber-700" : "text-emerald-700"}`}>
                {vibration.toFixed(2)} mm/s
              </span>
            </div>
            {/* Smooth Progress Meter */}
            <div className="relative w-full h-1.5 bg-slate-200 rounded-full overflow-hidden mt-1.5 border border-slate-100">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  isVibrationFault
                    ? "bg-rose-500"
                    : isVibrationHigh
                    ? "bg-amber-400"
                    : "bg-emerald-500"
                }`}
                style={{
                  width: `${Math.min(100, (vibration / vibrationFaultThreshold) * 100)}%`,
                }}
              />
            </div>
          </div>
        ) : (
          <div>
            <div className="text-[11px] text-slate-500 font-semibold">
              Output Volume
            </div>
            <div className="text-xs font-bold text-slate-900 mt-1 font-mono tabular-nums">
              {totalProduced} units
            </div>
          </div>
        )}
      </div>

      {/* Dynamic Process Readings */}
      <div className="my-1">
        <ReadingsGrid
          extra={effectiveReadings}
          subFacility={machine.sub_facility}
          signalDefinitions={machineDef?.signals}
        />
      </div>

      {/* Production Counter Footer & Inspect Action */}
      <div className="pt-3 mt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span>Good:</span>
            <strong className="text-slate-900 font-mono tabular-nums font-semibold">{good}</strong>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
            <span>Rej:</span>
            <strong className={reject > 0 ? "text-rose-600 font-mono tabular-nums font-bold" : "text-slate-500 font-mono tabular-nums"}>{reject}</strong>
          </span>
        </div>

        <div className="flex items-center gap-2">
          {totalProduced > 0 && (
            <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${Number(rejectRate) > 5 ? "bg-amber-50 text-amber-800 border-amber-200" : "bg-slate-100 text-slate-600 border-slate-200"}`}>
              {rejectRate}%
            </span>
          )}

          {onInspect && (
            <button
              onClick={onInspect}
              className="text-[11px] font-medium px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 hover:text-slate-900 border border-slate-200 transition-all flex items-center gap-1 cursor-pointer"
              title="Open Station Inspector"
            >
              <span>Inspect</span>
              <span>→</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
