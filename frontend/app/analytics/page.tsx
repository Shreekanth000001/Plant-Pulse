"use client";

import React, { useEffect, useState, useMemo } from "react";
import {
  fetchDefectRateByHour,
  fetchDefectRateByStage,
  getErrorMessage
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
  LineChart,
  Line,
} from "recharts";

const SHIFT_HOURS = new Set(["06", "14", "22", "6"]);

const STAGE_COLORS: Record<string, string> = {
  casting: "#06b6d4", // cyan
  housing: "#3b82f6", // blue
  assembly: "#a855f7", // purple
  qc: "#f43f5e", // rose
};

export default function AnalyticsPage() {
  const [hourlyData, setHourlyData] = useState<DefectRateByHour[]>([]);
  const [stageData, setStageData] = useState<DefectRateByStage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chartView, setChartView] = useState<"rate" | "volume">("rate");
  const isClient = useSyncExternalStore(() => () => {}, () => true, () => false);

  useEffect(() => {
    let isMounted = true;

    async function loadStats() {
      try {
        setLoading(true);
        setError(null);
        const [hourly, stages] = await Promise.all([
          fetchDefectRateByHour(),
          fetchDefectRateByStage(),
        ]);

        if (!isMounted) return;
        setHourlyData(hourly || []);
        setStageData(stages || []);
        setLoading(false);
      } catch (err: unknown) {
        if (!isMounted) return;
        setError(getErrorMessage(err, "Failed to load initial machine state"));
        setLoading(false);
      }
    }

    loadStats();
    return () => {
      isMounted = false;
    };
  }, []);

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
        <div className="w-8 h-8 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin" />
        <div className="text-xs text-slate-400">
          CALCULATING DEFECT RATES & ATTRIBUTION MATRICES...
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Top Header & Refresh */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 gap-3">
        <div>
          <h1 className="text-lg lg:text-xl font-bold font-mono text-slate-100 tracking-wide uppercase">
            Quality Analytics & Defect Intelligence
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Statistical breakdown of failure rates across 24-hour cycles and stage attribution.
          </p>
        </div>

        <button
          onClick={() => window.location.reload()}
          className="self-start sm:self-auto px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 text-slate-300 font-mono text-xs border border-slate-700 transition-colors flex items-center gap-1.5 cursor-pointer"
        >
          <span>↻</span>
          <span>Refresh Metrics</span>
        </button>
      </div>

      {error && (
        <div className="bg-amber-950/60 border border-amber-600/50 p-3 rounded-lg text-xs font-mono text-amber-300">
          ⚠️ Notice: {error}
        </div>
      )}

      {/* KPI Cards Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="scada-panel rounded-lg p-3.5">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Total Inspected
          </div>
          <div className="text-2xl font-bold font-mono text-slate-100 mt-1">
            {kpis.totalTested}
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">
            Full-line completions
          </div>
        </div>

        <div className="scada-panel rounded-lg p-3.5">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Overall Defect Rate
          </div>
          <div
            className={`text-2xl font-bold font-mono mt-1 ${
              Number(kpis.overallRate) > 5 ? "text-rose-400" : "text-emerald-400"
            }`}
          >
            {kpis.overallRate}%
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">
            {kpis.totalFailed} defect units
          </div>
        </div>

        <div className="scada-panel rounded-lg p-3.5">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Primary Defect Source
          </div>
          <div className="text-2xl font-bold font-mono text-amber-400 mt-1 uppercase">
            {kpis.topStage ? kpis.topStage.stage : "None"}
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">
            {kpis.topStage ? `${kpis.topStage.failures} failures recorded` : "Zero failures"}
          </div>
        </div>

        <div className="scada-panel rounded-lg p-3.5">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Shift Handover Bias
          </div>
          <div className="text-sm font-semibold font-mono text-cyan-400 mt-2">
            06:00 / 14:00 / 22:00
          </div>
          <div className="text-[10px] text-slate-500 font-mono mt-0.5">
            Monitored spike windows
          </div>
        </div>
      </div>

      {/* Main Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left (2 cols): Hourly Defect Rate Chart */}
        <div className="lg:col-span-2 scada-panel rounded-xl p-5 border-slate-800 flex flex-col justify-between">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 gap-2">
            <div>
              <h2 className="text-sm font-bold font-mono text-slate-200 uppercase tracking-wide">
                Defect Rate by Hour of Day
              </h2>
              <p className="text-xs text-slate-400">
                Surfaces temporal spikes and shift-change transition variances.
              </p>
            </div>

            {/* Toggle View */}
            <div className="flex items-center gap-1 bg-slate-900 p-1 rounded border border-slate-800 text-[11px] font-mono">
              <button
                onClick={() => setChartView("rate")}
                className={`px-2.5 py-1 rounded transition-colors ${
                  chartView === "rate"
                    ? "bg-cyan-950 text-cyan-300 font-semibold border border-cyan-500/40"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Defect Rate (%)
              </button>
              <button
                onClick={() => setChartView("volume")}
                className={`px-2.5 py-1 rounded transition-colors ${
                  chartView === "volume"
                    ? "bg-cyan-950 text-cyan-300 font-semibold border border-cyan-500/40"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Test Volumes
              </button>
            </div>
          </div>

          {/* Recharts Container */}
          <div className="mt-4 min-h-[320px] flex items-center justify-center">
            {isClient && formattedHourly.length > 0 ? (
              <div className="w-full h-[320px]">
                <ResponsiveContainer width="100%" height="100%">
                  {chartView === "rate" ? (
                    <BarChart data={formattedHourly} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis
                        dataKey="hourLabel"
                        stroke="#64748b"
                        tick={{ fill: "#94a3b8", fontSize: 11, fontFamily: "monospace" }}
                      />
                      <YAxis
                        stroke="#64748b"
                        tick={{ fill: "#94a3b8", fontSize: 11, fontFamily: "monospace" }}
                        tickFormatter={(v) => `${v}%`}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#0d1320",
                          borderColor: "#334155",
                          borderRadius: "8px",
                          fontFamily: "monospace",
                          fontSize: "12px",
                        }}
                        formatter={(val) => [`${val}%`, "Defect Rate"]}
                        labelFormatter={(label) => `Hour: ${label}`}
                      />
                      <ReferenceLine y={4} stroke="#eab308" strokeDasharray="3 3" label={{ value: "Base 4%", fill: "#ca8a04", fontSize: 10 }} />
                      <Bar dataKey="ratePercent" radius={[4, 4, 0, 0]}>
                        {formattedHourly.map((entry, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={entry.isShiftChange ? "#f43f5e" : "#06b6d4"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  ) : (
                    <LineChart data={formattedHourly} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis
                        dataKey="hourLabel"
                        stroke="#64748b"
                        tick={{ fill: "#94a3b8", fontSize: 11, fontFamily: "monospace" }}
                      />
                      <YAxis
                        stroke="#64748b"
                        tick={{ fill: "#94a3b8", fontSize: 11, fontFamily: "monospace" }}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#0d1320",
                          borderColor: "#334155",
                          borderRadius: "8px",
                          fontFamily: "monospace",
                          fontSize: "12px",
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="total_tested"
                        name="Total Inspected"
                        stroke="#38bdf8"
                        strokeWidth={2}
                        dot={{ r: 3, fill: "#38bdf8" }}
                      />
                      <Line
                        type="monotone"
                        dataKey="failed"
                        name="Failed"
                        stroke="#f43f5e"
                        strokeWidth={2}
                        dot={{ r: 3, fill: "#f43f5e" }}
                      />
                    </LineChart>
                  )}
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="text-center py-12 flex flex-col items-center gap-2">
                <span className="text-2xl">📊</span>
                <span className="text-xs font-mono text-slate-400">
                  Not enough hourly inspection data yet.
                </span>
                <span className="text-[11px] text-slate-500 font-mono">
                  Data accumulates as units cycle through QC testing.
                </span>
              </div>
            )}
          </div>

          {/* Shift Handover Legend */}
          <div className="pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-[11px] font-mono text-slate-400">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm bg-cyan-500" />
                Normal Hours
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm bg-rose-500" />
                Shift Change Hours (06:00, 14:00, 22:00)
              </span>
            </div>
            <span className="text-slate-500">
              Pattern: Higher defect probability occurs near shift handover windows.
            </span>
          </div>
        </div>

        {/* Right (1 col): Defect Rate by Stage */}
        <div className="scada-panel rounded-xl p-5 border-slate-800 flex flex-col justify-between">
          <div>
            <div className="pb-3 border-b border-slate-800">
              <h2 className="text-sm font-bold font-mono text-slate-200 uppercase tracking-wide">
                Attribution by Stage
              </h2>
              <p className="text-xs text-slate-400">
                Which stage caused the most QC failures.
              </p>
            </div>

            {/* Stage Bar Chart */}
            <div className="mt-4 min-h-[160px] flex items-center justify-center">
              {isClient && stageData.length > 0 && totalStageFailures > 0 ? (
                <div className="w-full h-[180px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      layout="vertical"
                      data={stageData}
                      margin={{ top: 5, right: 20, left: 20, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis type="number" stroke="#64748b" tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "monospace" }} />
                      <YAxis
                        type="category"
                        dataKey="stage"
                        stroke="#64748b"
                        tick={{ fill: "#e2e8f0", fontSize: 11, fontFamily: "monospace" }}
                        tickFormatter={(v) => v.toUpperCase()}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#0d1320",
                          borderColor: "#334155",
                          borderRadius: "8px",
                          fontFamily: "monospace",
                          fontSize: "12px",
                        }}
                      />
                      <Bar dataKey="failures" radius={[0, 4, 4, 0]}>
                        {stageData.map((entry, index) => (
                          <Cell
                            key={`stage-cell-${index}`}
                            fill={STAGE_COLORS[entry.stage.toLowerCase()] || "#06b6d4"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="text-center py-6 flex flex-col items-center gap-1 text-xs font-mono text-slate-400">
                  <span className="text-slate-500 italic">No defects recorded yet</span>
                </div>
              )}
            </div>

            {/* Ranked Stage Breakdown List */}
            <div className="mt-4 flex flex-col gap-2">
              <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
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
                        className="p-2.5 rounded bg-slate-950/70 border border-slate-800/80 flex items-center justify-between text-xs font-mono"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-slate-500 text-[10px]">#{idx + 1}</span>
                          <span className="font-semibold text-slate-200 uppercase">
                            {item.stage}
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-slate-400">
                            <strong className="text-rose-400">{item.failures}</strong> failures
                          </span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400">
                            {pct}%
                          </span>
                        </div>
                      </div>
                    );
                  })
              ) : (
                <div className="text-xs text-slate-500 italic font-mono py-2">
                  No stage attribution records.
                </div>
              )}
            </div>
          </div>

          <div className="pt-3 mt-4 border-t border-slate-800/80 text-[10px] font-mono text-slate-500">
            Attribution based on maximum normalized anomaly score across unit process stages.
          </div>
        </div>
      </div>
    </div>
  );
}
