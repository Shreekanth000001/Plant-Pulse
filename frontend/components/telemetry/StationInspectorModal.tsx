import React, { useEffect, useRef, useState, useMemo, useSyncExternalStore } from "react";
import Link from "next/link";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { MachineStatus, MachineDefinition } from "../../types/factory";
import { ReadingsGrid } from "./ReadingsGrid";
import { fetchSignalHistory, getErrorMessage } from "../../lib/api";
import {
  buildHistoryQueryParams,
  insertTimeGaps,
  safeSessionStorageGet,
  safeLocalStorageGet,
} from "../../lib/plant-utils";

interface StationInspectorModalProps {
  machineId: string | null;
  machine: MachineStatus | null;
  machineDef?: MachineDefinition;
  plantId?: string;
  onClose: () => void;
}

export function StationInspectorModal({
  machineId,
  machine,
  machineDef,
  plantId,
  onClose,
}: StationInspectorModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previousActiveElement = document.activeElement as HTMLElement | null;

    // Focus the first focusable element inside the modal on open
    const focusable = modalRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable && focusable.length > 0) {
      focusable[0].focus();
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }

      // Trap Tab key within modal
      if (e.key === "Tab" && modalRef.current) {
        const focusables = Array.from(
          modalRef.current.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          )
        ).filter((el) => !el.hasAttribute("disabled") && el.offsetParent !== null);

        if (focusables.length === 0) return;

        const first = focusables[0];
        const last = focusables[focusables.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousActiveElement?.focus();
    };
  }, [onClose]);

  const effectivePlantId =
    plantId || safeLocalStorageGet("plantpulse_active_plant", "plant_demo_membrane");

  const numericSignals = useMemo(() => {
    if (machineDef?.signals && machineDef.signals.length > 0) {
      return machineDef.signals.filter(
        (s) => s.data_type === "float" || s.data_type === "int"
      );
    }
    const extraEntries = Object.entries(machine?.extra || {});
    return extraEntries
      .filter(([, val]) => typeof val === "number")
      .map(([code]) => ({
        signal_code: code,
        name: code.replace(/_/g, " "),
        unit: "",
        data_type: "float",
      }));
  }, [machineDef, machine]);

  const [manualSignalCode, setManualSignalCode] = useState<string | null>(null);
  const selectedSignalCode =
    manualSignalCode && numericSignals.some((s) => s.signal_code === manualSignalCode)
      ? manualSignalCode
      : numericSignals[0]?.signal_code || "";

  const [rangePreset, setRangePreset] = useState<"1h" | "6h" | "12h" | "24h">("1h");

  const isClient = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false
  );

  const [historyData, setHistoryData] = useState<
    Array<{
      bucket_start?: string;
      timeLabel: string;
      count?: number | null;
      avg: number | null;
      min?: number | null;
      max?: number | null;
      last?: number | null;
    }>
  >([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyStats, setHistoryStats] = useState<{
    min: number | null;
    max: number | null;
    avg: number | null;
    last: number | null;
    totalPoints: number;
  } | null>(null);

  useEffect(() => {
    let isMounted = true;

    if (!machineId || !selectedSignalCode) {
      return () => {
        isMounted = false;
      };
    }

    const loadData = async () => {
      setHistoryLoading(true);
      setHistoryError(null);
      try {
        const token = safeSessionStorageGet(
          `plantpulse_viewer_token_${effectivePlantId}`,
          null
        );
        const params = buildHistoryQueryParams({ rangePreset, points: 300 });
        const res = await fetchSignalHistory(
          effectivePlantId,
          machineId,
          selectedSignalCode,
          params,
          token
        );

        if (!isMounted) return;

        const gapped = insertTimeGaps(res.data, res.bucket_sec);
        const formatted = gapped.map((pt) => {
          const rawTs = pt.bucket_start || "";
          const d = new Date(rawTs);
          const timeLabel = isNaN(d.getTime())
            ? rawTs
            : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
          return {
            ...pt,
            timeLabel,
          };
        });

        let sum = 0;
        let count = 0;
        let minVal: number | null = null;
        let maxVal: number | null = null;
        let lastVal: number | null = null;

        for (const pt of res.data) {
          if (pt.avg !== null && pt.count !== null && pt.count > 0) {
            sum += pt.avg * pt.count;
            count += pt.count;
            if (minVal === null || (pt.min !== null && pt.min < minVal)) minVal = pt.min;
            if (maxVal === null || (pt.max !== null && pt.max > maxVal)) maxVal = pt.max;
            if (pt.last !== null) lastVal = pt.last;
          }
        }

        setHistoryData(formatted);
        setHistoryStats(
          count > 0
            ? {
                min: minVal,
                max: maxVal,
                avg: Number((sum / count).toFixed(2)),
                last: lastVal,
                totalPoints: count,
              }
            : null
        );
      } catch (err: unknown) {
        if (!isMounted) return;
        setHistoryError(getErrorMessage(err, "Failed to load telemetry history"));
      } finally {
        if (isMounted) setHistoryLoading(false);
      }
    };

    loadData();
    return () => {
      isMounted = false;
    };
  }, [effectivePlantId, machineId, selectedSignalCode, rangePreset]);

  if (!machineId || !machine) return null;

  const displayName = machine.name || machineId;
  const state = machine.machine_state?.toUpperCase() || "OFFLINE";
  const isStarved = machine.starved;
  const selectedSignalDef = numericSignals.find(
    (s) => s.signal_code === selectedSignalCode
  );

  let stateColor = "text-slate-600 bg-slate-100 border-slate-200";
  if (state === "FAULT") {
    stateColor = "text-rose-700 bg-rose-50 border-rose-200";
  } else if (state === "RUNNING") {
    stateColor = "text-emerald-700 bg-emerald-50 border-emerald-200";
  } else if (state === "IDLE" || isStarved) {
    stateColor = "text-amber-800 bg-amber-50 border-amber-200";
  }

  const vibration = machine.vibration ?? null;
  const vibrationFaultThreshold = 7.0;
  const isVibrationFault = vibration !== null && vibration >= vibrationFaultThreshold;
  const isVibrationHigh = vibration !== null && vibration > 4.5;

  const good = machine.good_count ?? 0;
  const reject = machine.reject_count ?? 0;
  const total = good + reject;
  const scrapRate = total > 0 ? ((reject / total) * 100).toFixed(1) : "0.0";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs animate-fadeIn"
      onClick={onClose}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="station-inspector-title"
        className="bg-white rounded-3xl w-full max-w-2xl border border-slate-200 shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Top Bar */}
        <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/80">
          <div className="flex items-center gap-3.5">
            <div className="w-11 h-11 rounded-2xl bg-blue-100/70 border border-blue-200 flex items-center justify-center text-blue-700 font-mono font-bold text-sm shadow-xs">
              {(machineId || "").toUpperCase()}
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h3
                  id="station-inspector-title"
                  className="text-lg font-bold text-slate-900 tracking-tight"
                >
                  {displayName}
                </h3>
                <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border capitalize ${stateColor}`}>
                  {isStarved ? "Starved" : state.toLowerCase()}
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5 capitalize">
                Sub-facility: {machine.sub_facility} Station • Live Telemetry Stream
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            aria-label="Close station inspector"
            className="w-9 h-9 rounded-xl bg-white hover:bg-slate-100 text-slate-500 hover:text-slate-800 border border-slate-200 flex items-center justify-center transition-all cursor-pointer shadow-2xs"
          >
            ✕
          </button>
        </div>

        {/* Modal Scrollable Body */}
        <div className="p-6 overflow-y-auto flex flex-col gap-6">
          {/* Active Unit Banner */}
          <div className="bg-slate-50/70 rounded-2xl p-4 flex items-center justify-between border border-slate-200">
            <div>
              <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                Currently Processing Unit
              </div>
              {machine.current_unit_id ? (
                <div className="flex items-center gap-2 mt-1">
                  <span className="font-mono text-sm font-bold text-blue-600">
                    {machine.current_unit_id}
                  </span>
                  {machine.phase && (
                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-white text-slate-700 border border-slate-200">
                      Phase: {machine.phase}
                    </span>
                  )}
                </div>
              ) : (
                <div className="text-xs text-slate-400 italic mt-1 font-sans">
                  Station currently waiting for incoming buffer unit.
                </div>
              )}
            </div>

            {machine.current_unit_id && (
              <Link
                href={`/units/${encodeURIComponent(machine.current_unit_id)}`}
                className="px-3.5 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold shadow-xs transition-all flex items-center gap-1.5"
              >
                <span>Trace Unit Journey</span>
                <span>→</span>
              </Link>
            )}
          </div>

          {/* Mechanical Diagnostics & Vibration Wear */}
          <div className="bg-slate-50/70 rounded-2xl p-5 flex flex-col gap-3 border border-slate-200">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 tracking-tight flex items-center gap-2">
                <span>Mechanical Bearing & Motor Vibration</span>
                <span className="text-[10px] text-slate-500 font-normal">
                  (Safety limit: 7.0 mm/s)
                </span>
              </span>
              <span
                className={`font-mono text-xs font-bold ${
                  isVibrationFault
                    ? "text-rose-600"
                    : isVibrationHigh
                    ? "text-amber-700"
                    : "text-emerald-700"
                }`}
              >
                {vibration !== null ? `${vibration.toFixed(2)} mm/s` : "Normal"}
              </span>
            </div>

            {/* Vibration progress gauge */}
            <div className="w-full bg-slate-200 rounded-full h-2.5 overflow-hidden border border-slate-100">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  isVibrationFault
                    ? "bg-rose-500"
                    : isVibrationHigh
                    ? "bg-amber-400"
                    : "bg-emerald-500"
                }`}
                style={{
                  width: `${Math.min(
                    100,
                    vibration !== null ? (vibration / vibrationFaultThreshold) * 100 : 25
                  )}%`,
                }}
              />
            </div>

            <div className="flex items-center justify-between text-[11px] text-slate-500">
              <span>Baseline: 1.5 - 2.5 mm/s</span>
              <span>Degradation: {machine.vibration_wear_level ? `${(machine.vibration_wear_level * 100).toFixed(0)}%` : "Nominal"}</span>
            </div>
          </div>

          {/* Process Telemetry Parameters */}
          <div className="flex flex-col gap-2.5">
            <div className="text-xs font-bold text-slate-900 tracking-tight">
              Streaming Process Sensor Readings & Setpoints
            </div>
            <ReadingsGrid
              extra={machine.extra || {}}
              subFacility={machine.sub_facility}
              signalDefinitions={machineDef?.signals}
            />
          </div>

          {/* Signal Telemetry History Graph */}
          <div className="bg-slate-50/70 rounded-2xl p-5 border border-slate-200 flex flex-col gap-4">
            {/* Header: Title, Signal Select & Range Presets */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <div className="text-xs font-bold text-slate-900 tracking-tight flex items-center gap-2">
                  <span>Signal Telemetry History</span>
                  <span className="text-[10px] text-slate-400 font-normal">
                    (Aggregated time-series)
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  Continuous process variable analysis and trend detection.
                </p>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {/* Signal Selector */}
                {numericSignals.length > 0 && (
                  <select
                    value={selectedSignalCode}
                    onChange={(e) => setManualSignalCode(e.target.value)}
                    aria-label="Select telemetry signal"
                    className="text-xs font-medium bg-white text-slate-700 border border-slate-200 rounded-xl px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500/20 shadow-2xs cursor-pointer"
                  >
                    {numericSignals.map((s) => (
                      <option key={s.signal_code} value={s.signal_code}>
                        {s.name || s.signal_code} {s.unit ? `(${s.unit})` : ""}
                      </option>
                    ))}
                  </select>
                )}

                {/* Range Preset Buttons */}
                <div
                  className="flex items-center p-0.5 rounded-xl bg-slate-200/80 border border-slate-200 text-xs shadow-inner"
                  role="group"
                  aria-label="Time range presets"
                >
                  {(["1h", "6h", "12h", "24h"] as const).map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => setRangePreset(preset)}
                      className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                        rangePreset === preset
                          ? "bg-white text-blue-700 shadow-2xs font-semibold"
                          : "text-slate-600 hover:text-slate-900"
                      }`}
                      aria-pressed={rangePreset === preset}
                    >
                      {preset}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Quick Stats Bar (Min / Avg / Max / Last) */}
            {historyStats && (
              <div className="grid grid-cols-4 gap-2 pt-1">
                <div className="bg-white rounded-xl p-2.5 border border-slate-200/90 shadow-2xs">
                  <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">Min</span>
                  <span className="text-xs font-mono font-bold text-slate-700 mt-0.5 block truncate">
                    {historyStats.min !== null ? historyStats.min : "—"} {selectedSignalDef?.unit || ""}
                  </span>
                </div>
                <div className="bg-white rounded-xl p-2.5 border border-slate-200/90 shadow-2xs">
                  <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">Avg</span>
                  <span className="text-xs font-mono font-bold text-blue-700 mt-0.5 block truncate">
                    {historyStats.avg !== null ? historyStats.avg : "—"} {selectedSignalDef?.unit || ""}
                  </span>
                </div>
                <div className="bg-white rounded-xl p-2.5 border border-slate-200/90 shadow-2xs">
                  <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">Max</span>
                  <span className="text-xs font-mono font-bold text-slate-700 mt-0.5 block truncate">
                    {historyStats.max !== null ? historyStats.max : "—"} {selectedSignalDef?.unit || ""}
                  </span>
                </div>
                <div className="bg-white rounded-xl p-2.5 border border-slate-200/90 shadow-2xs">
                  <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">Latest</span>
                  <span className="text-xs font-mono font-bold text-slate-900 mt-0.5 block truncate">
                    {historyStats.last !== null ? historyStats.last : "—"} {selectedSignalDef?.unit || ""}
                  </span>
                </div>
              </div>
            )}

            {/* Chart / Loading / Empty State Area */}
            <div className="w-full">
              {historyLoading ? (
                <div
                  className="h-44 w-full bg-white/70 border border-slate-200/80 rounded-2xl flex flex-col items-center justify-center text-xs text-slate-400 gap-2 animate-pulse"
                  aria-busy="true"
                  aria-live="polite"
                >
                  <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                  <span>Loading telemetry history...</span>
                </div>
              ) : historyError ? (
                <div
                  className="h-44 w-full bg-rose-50 border border-rose-200 rounded-2xl p-4 flex flex-col items-center justify-center text-xs text-rose-700 text-center"
                  role="alert"
                >
                  <span className="font-semibold">Unable to load telemetry history</span>
                  <span className="text-rose-500 mt-1">{historyError}</span>
                </div>
              ) : !selectedSignalCode || numericSignals.length === 0 ? (
                <div className="h-44 w-full bg-white border border-dashed border-slate-200 rounded-2xl p-6 flex flex-col items-center justify-center text-center">
                  <div className="text-xs font-semibold text-slate-600">No numeric signals available</div>
                  <div className="text-[11px] text-slate-400 mt-1">
                    This machine does not define continuous telemetry signals.
                  </div>
                </div>
              ) : historyData.length === 0 || !historyStats ? (
                <div
                  className="h-44 w-full bg-white border border-dashed border-slate-200 rounded-2xl p-6 flex flex-col items-center justify-center text-center"
                  role="status"
                >
                  <div className="w-8 h-8 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 text-sm mb-1.5 font-mono">
                    ∅
                  </div>
                  <div className="text-xs font-semibold text-slate-700">No telemetry recorded in this time range</div>
                  <div className="text-[11px] text-slate-400 mt-1 max-w-xs">
                    Historical sensor readings will appear once data is published for this machine and signal.
                  </div>
                </div>
              ) : isClient ? (
                <div
                  className="h-44 w-full bg-white rounded-2xl border border-slate-200 p-2 shadow-2xs"
                  role="region"
                  aria-label="Signal history chart"
                >
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart
                      data={historyData}
                      margin={{ top: 8, right: 12, left: -22, bottom: 0 }}
                    >
                      <defs>
                        <linearGradient id="signalHistoryGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis
                        dataKey="timeLabel"
                        stroke="#94a3b8"
                        tick={{ fill: "#64748b", fontSize: 10 }}
                        minTickGap={28}
                      />
                      <YAxis
                        stroke="#94a3b8"
                        tick={{ fill: "#64748b", fontSize: 10 }}
                        domain={["auto", "auto"]}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#ffffff",
                          borderColor: "#e2e8f0",
                          borderRadius: "12px",
                          fontSize: "12px",
                          boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
                        }}
                        formatter={(val: unknown) => [
                          val !== null && typeof val === "number"
                            ? `${val.toFixed(2)} ${selectedSignalDef?.unit || ""}`.trim()
                            : "No data",
                          selectedSignalDef?.name || selectedSignalCode,
                        ]}
                        labelFormatter={(label) => `Time: ${label}`}
                      />
                      <Area
                        type="monotone"
                        dataKey="avg"
                        stroke="#2563eb"
                        strokeWidth={2}
                        fill="url(#signalHistoryGradient)"
                        connectNulls={false}
                        dot={false}
                        activeDot={{ r: 4, stroke: "#1d4ed8" }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-44 w-full bg-white rounded-2xl border border-slate-200" />
              )}
            </div>
          </div>

          {/* Shift Production Counters */}
          <div className="grid grid-cols-3 gap-3 pt-2">
            <div className="bg-slate-50 border border-slate-200 rounded-2xl p-3.5 flex flex-col justify-between">
              <span className="text-[11px] font-semibold text-slate-500">Total Produced</span>
              <span className="text-xl font-bold font-mono text-slate-900 mt-1">
                {total}
              </span>
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-2xl p-3.5 flex flex-col justify-between">
              <span className="text-[11px] font-semibold text-slate-500">Good Units</span>
              <span className="text-xl font-bold font-mono text-emerald-700 mt-1">
                {good}
              </span>
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-2xl p-3.5 flex flex-col justify-between">
              <span className="text-[11px] font-semibold text-slate-500">Scrap Rate</span>
              <span className={`text-xl font-bold font-mono mt-1 ${Number(scrapRate) > 5 ? "text-amber-800" : "text-slate-700"}`}>
                {scrapRate}%
              </span>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="p-4 border-t border-slate-100 bg-slate-50/80 flex items-center justify-between text-xs text-slate-500">
          <span>Tick: {machine.timestamp ? new Date(machine.timestamp).toLocaleTimeString() : "Live stream"}</span>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-medium transition-colors cursor-pointer shadow-xs"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
