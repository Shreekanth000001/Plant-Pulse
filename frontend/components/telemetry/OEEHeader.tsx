"use client";

import React, { useMemo } from "react";
import { MachineStatus } from "../../types/factory";

interface OEEHeaderProps {
  machines: Record<string, MachineStatus>;
}

export function OEEHeader({ machines }: OEEHeaderProps) {
  const machineList = useMemo(() => Object.values(machines), [machines]);

  const {
    availability,
    performance,
    quality,
    oee,
    runningCount,
    starvedCount,
    faultCount,
    totalGood,
    totalReject,
    totalProduced,
  } = useMemo(() => {
    let running = 0;
    let starved = 0;
    let fault = 0;
    let good = 0;
    let reject = 0;
    let totalVibration = 0;
    let vibrationCount = 0;

    for (const m of machineList) {
      const state = m.machine_state?.toUpperCase();
      if (state === "FAULT") fault++;
      else if (m.starved) starved++;
      else if (state === "RUNNING" || state === "TESTING") running++;

      good += m.good_count ?? 0;
      reject += m.reject_count ?? 0;

      if (typeof m.vibration === "number") {
        totalVibration += m.vibration;
        vibrationCount++;
      }
    }

    const total = machineList.length || 1;
    // Availability: fraction of machines currently running/operational
    const avail = (running / total) * 100;

    // Quality: first pass yield rate
    const totalOut = good + reject;
    const qual = totalOut > 0 ? (good / totalOut) * 100 : 100;

    // Performance: operating efficiency considering vibration wear and starving
    const avgVib = vibrationCount > 0 ? totalVibration / vibrationCount : 2.0;
    // baseline is 2.0; penalize if vibration elevated
    const vibFactor = Math.max(0.7, Math.min(1.0, 1.0 - (Math.max(0, avgVib - 2.0) * 0.05)));
    const perf = (running > 0 ? (running / (running + starved * 0.5)) : 0) * 100 * vibFactor;

    // Overall OEE = Availability * Performance * Quality
    const computedOEE = Math.min(100, Math.max(0, (avail * perf * qual) / 10000));

    return {
      availability: Math.min(100, avail),
      performance: Math.min(100, perf),
      quality: Math.min(100, qual),
      oee: computedOEE,
      runningCount: running,
      starvedCount: starved,
      faultCount: fault,
      totalGood: good,
      totalReject: reject,
      totalProduced: totalOut,
    };
  }, [machineList]);

  // Determine OEE status badge
  let oeeLabel = "HEALTHY";
  let oeeBadgeColor = "text-emerald-400 bg-emerald-950/60 border-emerald-500/40";
  let oeeBarColor = "bg-emerald-500";

  if (oee >= 85) {
    oeeLabel = "WORLD CLASS";
    oeeBadgeColor = "text-cyan-300 bg-cyan-950/70 border-cyan-500/50";
    oeeBarColor = "bg-cyan-400";
  } else if (oee < 65) {
    oeeLabel = "ATTENTION REQUIRED";
    oeeBadgeColor = "text-amber-400 bg-amber-950/70 border-amber-500/50";
    oeeBarColor = "bg-amber-400";
  }

  return (
    <div className="scada-panel rounded-2xl p-5 lg:p-6 border-slate-800 flex flex-col gap-5 shadow-2xl bg-[#0b1120]/90">
      {/* Top Banner: OEE Headline and 3 Pillars */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 pb-4 border-b border-slate-800/80">
        {/* Main OEE Metric Card */}
        <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
              Line OEE Overall
            </span>
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded-full border font-bold ${oeeBadgeColor}`}
            >
              {oeeLabel}
            </span>
          </div>

          <div className="my-2 flex items-baseline gap-2">
            <span className="text-3xl lg:text-4xl font-extrabold font-mono tracking-tight text-slate-100">
              {oee.toFixed(1)}%
            </span>
            <span className="text-xs text-slate-500 font-mono">
              / Target: 85.0%
            </span>
          </div>

          {/* Progress bar */}
          <div className="w-full bg-slate-900 rounded-full h-2 overflow-hidden border border-slate-800">
            <div
              className={`h-full ${oeeBarColor} transition-all duration-500`}
              style={{ width: `${oee}%` }}
            />
          </div>
        </div>

        {/* Pillar 1: Availability */}
        <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-mono">
            <span className="text-slate-400 uppercase font-semibold">
              Availability
            </span>
            <span className="text-emerald-400 font-bold">
              {availability.toFixed(1)}%
            </span>
          </div>

          <div className="my-2">
            <div className="text-xl font-bold font-mono text-slate-100">
              {runningCount} / {machineList.length} Active
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5 flex items-center gap-2">
              <span className={starvedCount > 0 ? "text-amber-400" : "text-slate-500"}>
                {starvedCount} Starved
              </span>
              <span>•</span>
              <span className={faultCount > 0 ? "text-rose-400 font-bold" : "text-slate-500"}>
                {faultCount} Faults
              </span>
            </div>
          </div>

          <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden border border-slate-800">
            <div
              className="h-full bg-emerald-400 transition-all duration-500"
              style={{ width: `${availability}%` }}
            />
          </div>
        </div>

        {/* Pillar 2: Performance */}
        <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-mono">
            <span className="text-slate-400 uppercase font-semibold">
              Performance
            </span>
            <span className="text-cyan-400 font-bold">
              {performance.toFixed(1)}%
            </span>
          </div>

          <div className="my-2">
            <div className="text-xl font-bold font-mono text-slate-100">
              Nominal Speed
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              Cycle pacing synchrony & mechanical health
            </div>
          </div>

          <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden border border-slate-800">
            <div
              className="h-full bg-cyan-400 transition-all duration-500"
              style={{ width: `${performance}%` }}
            />
          </div>
        </div>

        {/* Pillar 3: Quality */}
        <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-mono">
            <span className="text-slate-400 uppercase font-semibold">
              Quality Yield
            </span>
            <span className="text-indigo-400 font-bold">
              {quality.toFixed(1)}%
            </span>
          </div>

          <div className="my-2">
            <div className="text-xl font-bold font-mono text-slate-100">
              {totalGood} Units Good
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              <span className={totalReject > 0 ? "text-rose-400" : "text-slate-500"}>
                {totalReject} Defect Flagged
              </span>{" "}
              ({totalProduced > 0 ? ((totalReject / totalProduced) * 100).toFixed(1) : 0}% scrap)
            </div>
          </div>

          <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden border border-slate-800">
            <div
              className="h-full bg-indigo-400 transition-all duration-500"
              style={{ width: `${quality}%` }}
            />
          </div>
        </div>
      </div>

      {/* Evocon Signature Shift Production Rhythm Strip */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs font-mono text-slate-400 gap-1">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="font-semibold text-slate-200 uppercase">
              Production Shift Activity Timeline (Evocon Shift View)
            </span>
          </div>
          <div className="flex items-center gap-4 text-[11px]">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" />
              Productive Running
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-amber-400" />
              Micro-Stop / Starved
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-rose-500" />
              Downtime / Fault
            </span>
          </div>
        </div>

        {/* Multi-segment visual timeline strip */}
        <div className="relative w-full h-4 bg-slate-950 rounded-lg overflow-hidden border border-slate-800 flex shadow-inner">
          {/* Segment blocks representing chronological shift history */}
          <div style={{ width: "24%" }} className="h-full bg-emerald-500 hover:opacity-90 transition-opacity" title="Shift Start: Normal Run (08:00 - 10:00)" />
          <div style={{ width: "4%" }} className="h-full bg-amber-400" title="Buffer Wait / Stage Sync (10:00 - 10:20)" />
          <div style={{ width: "32%" }} className="h-full bg-emerald-500" title="Steady High-Speed Output (10:20 - 13:00)" />
          <div style={{ width: "3%" }} className="h-full bg-amber-400" title="Shift Change Handover Window (14:00)" />
          <div style={{ width: "22%" }} className="h-full bg-emerald-500" title="Active Production Run (14:15 - 16:00)" />
          <div
            style={{ width: "15%" }}
            className={`h-full ${
              faultCount > 0 ? "bg-rose-500 animate-pulse" : starvedCount > 0 ? "bg-amber-400" : "bg-emerald-400"
            }`}
            title="Current Real-time Production Status"
          />
        </div>

        <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 px-1">
          <span>08:00 (Shift In)</span>
          <span>10:00</span>
          <span>12:00 (Mid-Shift)</span>
          <span className="text-amber-400/90 font-semibold">14:00 (Handover Spike)</span>
          <span>16:00 (Current)</span>
        </div>
      </div>
    </div>
  );
}
