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
    const vibFactor = Math.max(0.7, Math.min(1.0, 1.0 - (Math.max(0, avgVib - 2.0) * 0.05)));
    const perf = (running > 0 ? running / (running + starved * 0.5) : 0) * 100 * vibFactor;

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
  let oeeLabel = "Healthy";
  let oeeBadgeColor = "text-emerald-700 bg-emerald-50 border-emerald-200";
  let oeeGradient = "from-emerald-500 to-teal-500";

  if (oee >= 85) {
    oeeLabel = "World Class";
    oeeBadgeColor = "text-blue-700 bg-blue-50 border-blue-200";
    oeeGradient = "from-blue-600 via-indigo-600 to-blue-500";
  } else if (oee < 65) {
    oeeLabel = "Attention Required";
    oeeBadgeColor = "text-amber-800 bg-amber-50 border-amber-200";
    oeeGradient = "from-amber-500 to-orange-500";
  }

  return (
    <div className="bg-white border border-slate-200/90 rounded-3xl p-6 lg:p-7 flex flex-col gap-6 shadow-xs relative overflow-hidden transition-all duration-300">
      {/* Top Banner: OEE Headline and 3 Pillars */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 relative z-10">
        {/* Main OEE Metric Card */}
        <div className="bg-slate-50/70 border border-slate-200 hover:border-slate-300 hover:bg-white rounded-2xl p-5 flex flex-col justify-between transition-all duration-200 shadow-xs group">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-blue-100/70 border border-blue-200/60 flex items-center justify-center text-blue-700 shadow-xs">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Overall Line OEE
              </span>
            </div>
            <span
              className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full border ${oeeBadgeColor}`}
            >
              {oeeLabel}
            </span>
          </div>

          <div className="my-3 flex items-baseline gap-2">
            <span className="text-3xl lg:text-4xl font-bold tracking-tight text-slate-900 font-sans">
              {oee.toFixed(1)}%
            </span>
            <span className="text-xs text-slate-500 font-medium">
              / 85% Target
            </span>
          </div>

          {/* Progress bar */}
          <div className="w-full bg-slate-200/80 rounded-full h-2 overflow-hidden border border-slate-100">
            <div
              className={`h-full bg-gradient-to-r ${oeeGradient} rounded-full transition-all duration-700`}
              style={{ width: `${Math.min(100, oee)}%` }}
            />
          </div>
        </div>

        {/* Pillar 1: Availability */}
        <div className="bg-slate-50/70 border border-slate-200 hover:border-slate-300 hover:bg-white rounded-2xl p-5 flex flex-col justify-between transition-all duration-200 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-emerald-100/70 border border-emerald-200/60 flex items-center justify-center text-emerald-700 shadow-xs">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Availability
              </span>
            </div>
            <span className="text-xs font-bold text-emerald-700 font-mono">
              {availability.toFixed(1)}%
            </span>
          </div>

          <div className="my-3">
            <div className="text-lg font-bold text-slate-900">
              {runningCount} / {machineList.length} Operational
            </div>
            <div className="text-xs text-slate-500 mt-1 flex items-center gap-2">
              <span className={starvedCount > 0 ? "text-amber-700 font-medium" : "text-slate-500"}>
                {starvedCount} Starved
              </span>
              <span className="text-slate-300">•</span>
              <span className={faultCount > 0 ? "text-rose-600 font-medium" : "text-slate-500"}>
                {faultCount} Faults
              </span>
            </div>
          </div>

          <div className="w-full bg-slate-200/80 rounded-full h-2 overflow-hidden border border-slate-100">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 to-teal-500 rounded-full transition-all duration-700"
              style={{ width: `${Math.min(100, availability)}%` }}
            />
          </div>
        </div>

        {/* Pillar 2: Performance */}
        <div className="bg-slate-50/70 border border-slate-200 hover:border-slate-300 hover:bg-white rounded-2xl p-5 flex flex-col justify-between transition-all duration-200 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-sky-100/70 border border-sky-200/60 flex items-center justify-center text-sky-700 shadow-xs">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Performance
                </span>
                <span
                  className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200 cursor-help"
                  title="Proxy estimate: operating cycle pacing factored by mechanical vibration wear"
                >
                  EST.
                </span>
              </div>
            </div>
            <span className="text-xs font-bold text-sky-700 font-mono">
              {performance.toFixed(1)}%
            </span>
          </div>

          <div className="my-3">
            <div className="text-lg font-bold text-slate-900">
              Nominal Pacing
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Cycle synchrony & motor wear factor
            </div>
          </div>

          <div className="w-full bg-slate-200/80 rounded-full h-2 overflow-hidden border border-slate-100">
            <div
              className="h-full bg-gradient-to-r from-sky-500 to-blue-600 rounded-full transition-all duration-700"
              style={{ width: `${Math.min(100, performance)}%` }}
            />
          </div>
        </div>

        {/* Pillar 3: Quality */}
        <div className="bg-slate-50/70 border border-slate-200 hover:border-slate-300 hover:bg-white rounded-2xl p-5 flex flex-col justify-between transition-all duration-200 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-indigo-100/70 border border-indigo-200/60 flex items-center justify-center text-indigo-700 shadow-xs">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Quality Yield
              </span>
            </div>
            <span className="text-xs font-bold text-indigo-700 font-mono">
              {quality.toFixed(1)}%
            </span>
          </div>

          <div className="my-3">
            <div className="text-lg font-bold text-slate-900">
              {totalGood} Units Good
            </div>
            <div className="text-xs text-slate-500 mt-1">
              <span className={totalReject > 0 ? "text-rose-600 font-medium" : "text-slate-500"}>
                {totalReject} Flagged
              </span>{" "}
              ({totalProduced > 0 ? ((totalReject / totalProduced) * 100).toFixed(1) : 0}% scrap)
            </div>
          </div>

          <div className="w-full bg-slate-200/80 rounded-full h-2 overflow-hidden border border-slate-100">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-purple-600 rounded-full transition-all duration-700"
              style={{ width: `${Math.min(100, quality)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Live Line Operating Rhythm & Status Distribution (Data-Driven) */}
      <div className="bg-slate-50/70 border border-slate-200 rounded-2xl p-5 flex flex-col gap-3 relative z-10 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs text-slate-700 gap-2">
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            <span className="font-semibold text-slate-900 tracking-tight">
              Line Operating Rhythm
            </span>
            <span className="text-xs text-slate-500">
              (Live Station State Distribution)
            </span>
          </div>

          {/* Interactive Legend Pills with Real Live Counts */}
          <div className="flex items-center gap-3 text-xs font-mono">
            <span className="flex items-center gap-1.5 text-slate-700">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
              <span>Running ({runningCount})</span>
            </span>
            <span className="flex items-center gap-1.5 text-slate-700">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-400" />
              <span>Starved ({starvedCount})</span>
            </span>
            <span className="flex items-center gap-1.5 text-slate-700">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
              <span>Faults ({faultCount})</span>
            </span>
            {machineList.length - runningCount - starvedCount - faultCount > 0 && (
              <span className="flex items-center gap-1.5 text-slate-700">
                <span className="w-2.5 h-2.5 rounded-full bg-slate-300" />
                <span>Idle ({machineList.length - runningCount - starvedCount - faultCount})</span>
              </span>
            )}
          </div>
        </div>

        {/* Real-time segmented distribution strip based on live telemetry */}
        <div className="relative w-full h-3.5 bg-slate-200 rounded-xl overflow-hidden border border-slate-300/60 flex shadow-inner">
          {runningCount > 0 && (
            <div
              style={{ width: `${(runningCount / (machineList.length || 1)) * 100}%` }}
              className="h-full bg-emerald-500 hover:brightness-105 transition-all duration-500"
              title={`Running: ${runningCount} stations (${((runningCount / (machineList.length || 1)) * 100).toFixed(0)}%)`}
            />
          )}
          {starvedCount > 0 && (
            <div
              style={{ width: `${(starvedCount / (machineList.length || 1)) * 100}%` }}
              className="h-full bg-amber-400 hover:brightness-105 transition-all duration-500"
              title={`Starved / Micro-stops: ${starvedCount} stations (${((starvedCount / (machineList.length || 1)) * 100).toFixed(0)}%)`}
            />
          )}
          {faultCount > 0 && (
            <div
              style={{ width: `${(faultCount / (machineList.length || 1)) * 100}%` }}
              className="h-full bg-rose-500 animate-pulse hover:brightness-105 transition-all duration-500"
              title={`Active Downtime / Faults: ${faultCount} stations (${((faultCount / (machineList.length || 1)) * 100).toFixed(0)}%)`}
            />
          )}
          {machineList.length - runningCount - starvedCount - faultCount > 0 && (
            <div
              style={{
                width: `${
                  ((machineList.length - runningCount - starvedCount - faultCount) /
                    (machineList.length || 1)) *
                  100
                }%`,
              }}
              className="h-full bg-slate-300 hover:brightness-105 transition-all duration-500"
              title={`Idle: ${machineList.length - runningCount - starvedCount - faultCount} stations`}
            />
          )}
        </div>

        <div className="flex items-center justify-between text-[11px] text-slate-500 px-0.5 font-mono">
          <span>0%</span>
          <span>Line Operational Balance ({runningCount} of {machineList.length} Active)</span>
          <span>100%</span>
        </div>
      </div>
    </div>
  );
}
