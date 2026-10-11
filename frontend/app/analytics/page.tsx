"use client";

import React, { useEffect, useState, useMemo } from "react";
import {
  fetchDefectRateByHour,
  fetchDefectRateByStage,
  getErrorMessage,
} from "../../lib/api";
import { DefectRateByHour, DefectRateByStage } from "../../types/factory";
import { useSyncExternalStore } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Cell,
  AreaChart,
  Area,
} from "recharts";

const SHIFT_HOURS = new Set(["06", "14", "22", "6"]);

const STAGE_COLORS: Record<string, string> = {
  casting: "#2563eb", // blue
  housing: "#6366f1", // indigo
  assembly: "#8b5cf6", // purple
  qc: "#f43f5e", // rose
};

export default function AnalyticsPage() {
  const [hourlyData, setHourlyData] = useState<DefectRateByHour[]>([]);
  const [stageData, setStageData] = useState<DefectRateByStage[]>([]);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [chartView, setChartView] = useState<"rate" | "volume">("rate");
  const isClient = useSyncExternalStore(() => () => {}, () => true, () => false);

  const loadStats = React.useCallback(async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      else setIsRefreshing(true);
      setError(null);
      const [hourly, stages] = await Promise.all([
        fetchDefectRateByHour(),
        fetchDefectRateByStage(),
      ]);

      setHourlyData(hourly || []);
      setStageData(stages || []);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err: unknown) {
      setError(getErrorMessage(err, "Failed to load analytics data"));
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function initialLoad() {
      try {
        const [hourly, stages] = await Promise.all([
          fetchDefectRateByHour(),
          fetchDefectRateByStage(),
        ]);
        if (!isMounted) return;
        setHourlyData(hourly || []);
        setStageData(stages || []);
        setLastUpdated(new Date().toLocaleTimeString());
        setLoading(false);
      } catch (err: unknown) {
        if (!isMounted) return;
        setError(getErrorMessage(err, "Failed to load analytics data"));
        setLoading(false);
      }
    }

    initialLoad();

    // Auto-refresh analytics data every 30 seconds
    const interval = setInterval(() => {
      loadStats(true);
    }, 30000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [loadStats]);

  // Format hourly data for display (percentages)
  const formattedHourly = useMemo(() => {
    return hourlyData.map((d) => ({
      ...d,
      hourLabel: `${d.hour.padStart(2, "0")}:00`,
      ratePercent: Number((d.defect_rate * 100).toFixed(1)),
      isShiftChange: SHIFT_HOURS.has(d.hour) || SHIFT_HOURS.has(d.hour.padStart(2, "0")),
    }));
  }, [hourlyData]);

  // Aggregate KPI metrics
  const kpis = useMemo(() => {
    let totalTested = 0;
    let totalFailed = 0;

    for (const h of hourlyData) {
      totalTested += h.total_tested;
      totalFailed += h.failed;
    }

    const overallRate = totalTested > 0 ? (totalFailed / totalTested) * 100 : 0;

    const sortedStages = [...stageData].sort((a, b) => b.failures - a.failures);
    const topStage = sortedStages.length > 0 && sortedStages[0].failures > 0 ? sortedStages[0] : null;

    return {
      totalTested,
      totalFailed,
      overallRate: overallRate.toFixed(1),
      topStage,
    };
  }, [hourlyData, stageData]);

  const totalStageFailures = useMemo(() => {
    return stageData.reduce((acc, s) => acc + s.failures, 0);
  }, [stageData]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3 font-mono">
        <div className="w-8 h-8 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
        <div className="text-xs text-slate-500 font-medium">
          Loading analytics & defect intelligence matrices...
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Top Header & Refresh */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-200/80 gap-3">
        <div>
          <h1 className="text-xl lg:text-2xl font-bold tracking-tight text-slate-900">
            Quality Analytics & Defect Intelligence
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Statistical breakdown of quality defect rates across 24-hour manufacturing cycles and root-cause stage attribution.
          </p>
        </div>

        <div className="flex items-center gap-3 self-start sm:self-auto">
          {lastUpdated && (
            <span className="text-[11px] font-mono text-slate-500 hidden md:inline">
              Synced: {lastUpdated} (30s auto-refresh)
            </span>
          )}
          <button
            onClick={() => loadStats(false)}
            disabled={isRefreshing}
            className="px-3.5 py-1.5 rounded-xl bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold border border-slate-200 transition-all flex items-center gap-2 cursor-pointer shadow-xs hover:border-slate-300 disabled:opacity-50"
          >
            <span className={isRefreshing ? "animate-spin" : ""}>↻</span>
            <span>{isRefreshing ? "Refreshing..." : "Refresh Data"}</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-amber-50 border border-amber-200 p-3.5 rounded-2xl text-xs text-amber-900 font-medium">
          ⚠️ Notice: {error}
        </div>
      )}

      {/* KPI Cards Strip (Snow & Evocon Clean Style) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1 */}
        <div className="bg-white rounded-2xl p-5 flex flex-col justify-between border border-slate-200/90 shadow-xs hover:shadow-md transition-all">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Total Inspected
            </span>
            <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-700 text-xs font-bold">
              ✓
            </div>
          </div>
          <div className="my-2">
            <div className="text-3xl font-bold text-slate-900 tracking-tight font-sans">
              {kpis.totalTested}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Full-line completions
            </div>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
            <div className="h-full bg-blue-600 rounded-full w-full" />
          </div>
        </div>

        {/* KPI 2 */}
        <div className="bg-white rounded-2xl p-5 flex flex-col justify-between border border-slate-200/90 shadow-xs hover:shadow-md transition-all">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Overall Defect Rate
            </span>
            <div className="w-8 h-8 rounded-lg bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-700 text-xs font-bold">
              %
            </div>
          </div>
          <div className="my-2">
            <div
              className={`text-3xl font-bold tracking-tight font-sans ${
                Number(kpis.overallRate) > 5 ? "text-rose-600" : "text-emerald-700"
              }`}
            >
              {kpis.overallRate}%
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {kpis.totalFailed} defect units isolated
            </div>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full rounded-full ${
                Number(kpis.overallRate) > 5 ? "bg-rose-500" : "bg-emerald-500"
              }`}
              style={{ width: `${Math.min(100, Number(kpis.overallRate) * 10)}%` }}
            />
          </div>
        </div>

        {/* KPI 3 */}
        <div className="bg-white rounded-2xl p-5 flex flex-col justify-between border border-slate-200/90 shadow-xs hover:shadow-md transition-all">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Primary Defect Source
            </span>
            <div className="w-8 h-8 rounded-lg bg-amber-50 border border-amber-200 flex items-center justify-center text-amber-800 text-xs font-bold">
              !
            </div>
          </div>
          <div className="my-2">
            <div className="text-3xl font-bold text-amber-800 tracking-tight capitalize font-sans">
              {kpis.topStage ? kpis.topStage.stage : "None"}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {kpis.topStage ? `${kpis.topStage.failures} failures attributed` : "Zero defect records"}
            </div>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
            <div className="h-full bg-amber-500 rounded-full w-3/4" />
          </div>
        </div>

        {/* KPI 4 */}
        <div className="bg-white rounded-2xl p-5 flex flex-col justify-between border border-slate-200/90 shadow-xs hover:shadow-md transition-all">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Shift Handover Bias
            </span>
            <div className="w-8 h-8 rounded-lg bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700 text-xs font-bold">
              ⏱
            </div>
          </div>
          <div className="my-2">
            <div className="text-xl font-bold text-slate-900 font-mono tracking-tight mt-1">
              06:00 / 14:00 / 22:00
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Handover transition spikes
            </div>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
            <div className="h-full bg-sky-500 rounded-full w-2/3" />
          </div>
        </div>
      </div>

      {/* Main Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left (2 cols): Hourly Defect Rate Chart */}
        <div className="lg:col-span-2 bg-white rounded-3xl p-6 border border-slate-200/90 flex flex-col justify-between shadow-xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 gap-3">
            <div>
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                Defect Rate by Hour of Day
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Surfaces temporal spikes and shift-change transition variances across line shifts.
              </p>
            </div>

            {/* Toggle View */}
            <div className="flex items-center p-1 rounded-xl bg-slate-100 border border-slate-200 text-xs shadow-inner">
              <button
                onClick={() => setChartView("rate")}
                className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                  chartView === "rate"
                    ? "bg-white text-blue-700 shadow-xs border border-slate-200 font-semibold"
                    : "text-slate-600 hover:text-slate-900 hover:bg-white/50"
                }`}
              >
                Defect Rate (%)
              </button>
              <button
                onClick={() => setChartView("volume")}
                className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                  chartView === "volume"
                    ? "bg-white text-blue-700 shadow-xs border border-slate-200 font-semibold"
                    : "text-slate-600 hover:text-slate-900 hover:bg-white/50"
                }`}
              >
                Test Volumes
              </button>
            </div>
          </div>

          {/* Recharts Container */}
          <div className="mt-6 min-h-[340px] flex items-center justify-center">
            {isClient && formattedHourly.length > 0 ? (
              <div className="w-full h-[340px]">
                <ResponsiveContainer width="100%" height="100%">
                  {chartView === "rate" ? (
                    <BarChart data={formattedHourly} margin={{ top: 15, right: 15, left: -15, bottom: 0 }}>
                      <defs>
                        <linearGradient id="normalHourGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.9} />
                          <stop offset="100%" stopColor="#1d4ed8" stopOpacity={0.6} />
                        </linearGradient>
                        <linearGradient id="shiftHourGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#f43f5e" stopOpacity={1} />
                          <stop offset="100%" stopColor="#be123c" stopOpacity={0.7} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.8} />
                      <XAxis
                        dataKey="hourLabel"
                        stroke="#94a3b8"
                        tick={{ fill: "#64748b", fontSize: 11, fontFamily: "sans-serif" }}
                      />
                      <YAxis
                        stroke="#94a3b8"
                        tick={{ fill: "#64748b", fontSize: 11, fontFamily: "sans-serif" }}
                        tickFormatter={(v) => `${v}%`}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#ffffff",
                          borderColor: "#e2e8f0",
                          borderRadius: "16px",
                          fontSize: "12px",
                          boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
                          color: "#0f172a",
                        }}
                        formatter={(val) => [`${val}%`, "Defect Rate"]}
                        labelFormatter={(label) => `Time: ${label}`}
                      />
                      <ReferenceLine
                        y={4}
                        stroke="#d97706"
                        strokeDasharray="4 4"
                        label={{ value: "Target Threshold (4%)", fill: "#b45309", fontSize: 11, position: "top" }}
                      />
                      <Bar dataKey="ratePercent" radius={[8, 8, 0, 0]}>
                        {formattedHourly.map((entry, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={entry.isShiftChange ? "url(#shiftHourGradient)" : "url(#normalHourGradient)"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  ) : (
                    <AreaChart data={formattedHourly} margin={{ top: 15, right: 15, left: -15, bottom: 0 }}>
                      <defs>
                        <linearGradient id="testedArea" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
                          <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.0} />
                        </linearGradient>
                        <linearGradient id="failedArea" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.3} />
                          <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.8} />
                      <XAxis
                        dataKey="hourLabel"
                        stroke="#94a3b8"
                        tick={{ fill: "#64748b", fontSize: 11 }}
                      />
                      <YAxis
                        stroke="#94a3b8"
                        tick={{ fill: "#64748b", fontSize: 11 }}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#ffffff",
                          borderColor: "#e2e8f0",
                          borderRadius: "16px",
                          fontSize: "12px",
                          boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
                          color: "#0f172a",
                        }}
                      />
                      <Area
                        type="monotone"
                        dataKey="total_tested"
                        name="Total Inspected"
                        stroke="#2563eb"
                        strokeWidth={2.5}
                        fill="url(#testedArea)"
                      />
                      <Area
                        type="monotone"
                        dataKey="failed"
                        name="Defects"
                        stroke="#e11d48"
                        strokeWidth={2.5}
                        fill="url(#failedArea)"
                      />
                    </AreaChart>
                  )}
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="text-center py-14 flex flex-col items-center gap-2">
                <span className="text-3xl">📊</span>
                <span className="text-xs text-slate-600 font-medium">
                  Awaiting hourly inspection telemetry data...
                </span>
                <span className="text-xs text-slate-400">
                  Data accumulates as units cycle through quality inspection.
                </span>
              </div>
            )}
          </div>

          {/* Shift Handover Legend */}
          <div className="pt-4 border-t border-slate-100 flex flex-wrap items-center justify-between text-xs text-slate-500 gap-2">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-md bg-blue-500" />
                Normal Operating Hours
              </span>
              <span className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-md bg-rose-500" />
                Shift Handover Windows (06:00, 14:00, 22:00)
              </span>
            </div>
            <span className="text-slate-400 text-[11px]">
              Tip: Elevated defect risk typically clusters around operator shift transfers.
            </span>
          </div>
        </div>

        {/* Right (1 col): Defect Rate by Stage */}
        <div className="bg-white rounded-3xl p-6 border border-slate-200/90 flex flex-col justify-between shadow-xs">
          <div>
            <div className="pb-4 border-b border-slate-100">
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                Attribution by Stage
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Root-cause attribution ranking by manufacturing sub-facility.
              </p>
            </div>

            {/* Stage Horizontal Bar Chart */}
            <div className="mt-5 min-h-[160px] flex items-center justify-center">
              {isClient && stageData.length > 0 && totalStageFailures > 0 ? (
                <div className="w-full h-[180px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      layout="vertical"
                      data={stageData}
                      margin={{ top: 5, right: 20, left: 20, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.8} />
                      <XAxis type="number" stroke="#94a3b8" tick={{ fill: "#64748b", fontSize: 10 }} />
                      <YAxis
                        type="category"
                        dataKey="stage"
                        stroke="#94a3b8"
                        tick={{ fill: "#1e293b", fontSize: 11, fontWeight: 600 }}
                        tickFormatter={(v) => v.toUpperCase()}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#ffffff",
                          borderColor: "#e2e8f0",
                          borderRadius: "14px",
                          fontSize: "12px",
                          boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
                          color: "#0f172a",
                        }}
                      />
                      <Bar dataKey="failures" radius={[0, 6, 6, 0]}>
                        {stageData.map((entry, index) => (
                          <Cell
                            key={`stage-cell-${index}`}
                            fill={STAGE_COLORS[entry.stage.toLowerCase()] || "#2563eb"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="text-center py-6 flex flex-col items-center gap-1 text-xs text-slate-500">
                  <span className="italic">No defects recorded yet</span>
                </div>
              )}
            </div>

            {/* Ranked Stage Breakdown List */}
            <div className="mt-5 flex flex-col gap-2.5">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Ranked Failure Attribution
              </span>
              {stageData.length > 0 ? (
                stageData
                  .sort((a, b) => b.failures - a.failures)
                  .map((item, idx) => {
                    const pct =
                      totalStageFailures > 0
                        ? ((item.failures / totalStageFailures) * 100).toFixed(1)
                        : "0.0";
                    return (
                      <div
                        key={item.stage}
                        className="p-3 rounded-2xl bg-slate-50 border border-slate-200/80 flex items-center justify-between text-xs hover:border-slate-300 transition-all shadow-2xs"
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="w-5 h-5 rounded-full bg-white text-slate-700 border border-slate-200 flex items-center justify-center text-[10px] font-bold shadow-xs">
                            #{idx + 1}
                          </span>
                          <span className="font-semibold text-slate-900 capitalize">
                            {item.stage}
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-slate-500">
                            <strong className="text-rose-600 font-mono font-bold">{item.failures}</strong> failures
                          </span>
                          <span className="text-xs font-mono font-semibold px-2 py-0.5 rounded-full bg-white text-slate-700 border border-slate-200 shadow-2xs">
                            {pct}%
                          </span>
                        </div>
                      </div>
                    );
                  })
              ) : (
                <div className="text-xs text-slate-400 italic py-2">
                  No stage attribution records.
                </div>
              )}
            </div>
          </div>

          <div className="pt-4 mt-4 border-t border-slate-100 text-[11px] text-slate-500">
            Attribution derived from maximum normalized sensor anomaly scores during unit manufacturing steps.
          </div>
        </div>
      </div>
    </div>
  );
}
