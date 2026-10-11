"use client";

import React from "react";
import Link from "next/link";
import { MachineStatus, KNOWN_MACHINES } from "../../types/factory";
import { ReadingsGrid } from "./ReadingsGrid";

interface MachineCardProps {
  machine: MachineStatus;
}

export function MachineCard({ machine }: MachineCardProps) {
  const machineMeta = KNOWN_MACHINES[machine.machine_id];
  const displayName = machine.name || machineMeta?.name || machine.machine_id;

  // Determine state color theme
  const state = machine.machine_state?.toUpperCase() || "IDLE";
  const isStarved = machine.starved;

  let stateBorder = "border-amber-500/30";
  let stateBadgeBg = "bg-amber-500/10 text-amber-300";
  let dotColor = "bg-amber-400";
  let panelHighlight = "";
  let accentBarColor = "bg-amber-400";

  if (state === "FAULT") {
    stateBorder = "border-rose-500/50";
    stateBadgeBg = "bg-rose-500/20 text-rose-300";
    dotColor = "bg-rose-500 animate-ping";
    panelHighlight = "shadow-[0_0_15px_-3px_rgba(244,63,94,0.3)] border-rose-900";
    accentBarColor = "bg-rose-500";
  } else if (state === "RUNNING") {
    stateBorder = "border-emerald-500/30";
    stateBadgeBg = "bg-emerald-500/15 text-emerald-300";
    dotColor = "bg-emerald-400 animate-pulse";
    accentBarColor = "bg-emerald-400";
  } else if (state === "TESTING") {
    stateBorder = "border-cyan-500/30";
    stateBadgeBg = "bg-cyan-500/15 text-cyan-300";
    dotColor = "bg-cyan-400 animate-pulse";
    accentBarColor = "bg-cyan-400";
  } else if (isStarved) {
    stateBadgeBg = "bg-amber-950/60 text-amber-300 border border-amber-500/40";
    accentBarColor = "bg-amber-400 animate-pulse";
  } else {
    accentBarColor = "bg-slate-700";
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

  return (
    <div
      className={`scada-panel rounded-lg p-3.5 flex flex-col justify-between transition-all duration-200 hover:border-slate-700 relative overflow-hidden ${panelHighlight}`}
    >
      {/* Evocon-inspired top status accent line */}
      <div className={`absolute top-0 left-0 right-0 h-1 ${accentBarColor}`} />

      {/* Top Header: ID, Name, State Badge */}
      <div className="flex items-start justify-between gap-2 pb-2.5 border-b border-slate-800 pt-1">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] font-bold text-slate-400 tracking-wider">
              {machine.machine_id.toUpperCase()}
            </span>
            <span className="text-slate-600">•</span>
            <h3 className="text-xs font-semibold text-slate-200 tracking-tight truncate max-w-[170px]">
              {displayName}
            </h3>
          </div>

          {/* Phase and starved tag */}
          <div className="flex items-center gap-1.5 mt-1">
            {machine.phase && (
              <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-300 border border-slate-700/60">
                PHASE: {machine.phase}
              </span>
            )}
            {isStarved && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-950/80 text-amber-300 border border-amber-600/50 flex items-center gap-1 animate-pulse">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                STARVED
              </span>
            )}
          </div>
        </div>

        {/* State Pill */}
        <div
          className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-mono font-medium ${stateBadgeBg} ${stateBorder}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
          <span>{state}</span>
        </div>
      </div>

      {/* Primary Telemetry Metrics Row */}
      <div className="grid grid-cols-2 gap-2 my-2.5 py-2 px-2.5 bg-slate-950/60 rounded border border-slate-800/80">
        {/* Current Unit */}
        <div>
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Active Unit
          </div>
          {currentUnit ? (
            <Link
              href={`/units/${encodeURIComponent(currentUnit)}`}
              className="inline-flex items-center gap-1 font-mono text-xs font-medium text-cyan-400 hover:text-cyan-300 hover:underline mt-0.5 transition-colors truncate max-w-full"
            >
              <span className="truncate">{currentUnit}</span>
              <svg className="w-3 h-3 opacity-70 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </Link>
          ) : (
            <div className="font-mono text-xs text-slate-600 mt-0.5 italic">
              [EMPTY]
            </div>
          )}
        </div>

        {/* Vibration / Wear (if present for machine) */}
        {vibration !== null ? (
          <div>
            <div className="flex items-center justify-between text-[10px] text-slate-500 uppercase font-mono">
              <span>Vibration</span>
              <span className={isVibrationFault ? "text-rose-400 font-bold" : isVibrationHigh ? "text-amber-400" : "text-slate-400"}>
                {vibration.toFixed(2)} mm/s
              </span>
            </div>
            {/* Mini Vibration Meter */}
            <div className="relative w-full h-1.5 bg-slate-900 rounded-full overflow-hidden mt-1.5 border border-slate-800">
              <div
                className={`h-full transition-all duration-300 ${
                  isVibrationFault
                    ? "bg-rose-500"
                    : isVibrationHigh
                    ? "bg-amber-400"
                    : "bg-emerald-400"
                }`}
                style={{
                  width: `${Math.min(100, (vibration / vibrationFaultThreshold) * 100)}%`,
                }}
              />
            </div>
          </div>
        ) : (
          <div>
            <div className="text-[10px] text-slate-500 uppercase font-mono">
              Throughput
            </div>
            <div className="font-mono text-xs text-slate-300 mt-0.5">
              {totalProduced} units
            </div>
          </div>
        )}
      </div>

      {/* Dynamic Process Readings from `extra` */}
      <div className="my-1">
        <ReadingsGrid extra={machine.extra || {}} subFacility={machine.sub_facility} />
      </div>

      {/* Production Counter Footer */}
      <div className="pt-2.5 mt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] font-mono text-slate-400">
        <div className="flex items-center gap-3">
          <span title="Units passed or processed cleanly">
            GOOD: <strong className="text-emerald-400">{good}</strong>
          </span>
          <span title="Units flagged or rejected">
            REJ: <strong className={reject > 0 ? "text-rose-400" : "text-slate-500"}>{reject}</strong>
          </span>
        </div>

        {totalProduced > 0 && (
          <span className="text-[10px] text-slate-500">
            SCRAP: <span className={Number(rejectRate) > 5 ? "text-amber-400" : "text-slate-400"}>{rejectRate}%</span>
          </span>
        )}
      </div>
    </div>
  );
}
