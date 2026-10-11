"use client";

import React, { useEffect, useState, useMemo, Suspense } from "react";
import Link from "next/link";
import { useRouter, useParams } from "next/navigation";
import { fetchUnitHistory, ApiError } from "../../../lib/api";
import {
  UnitHistoryResponse,
  KNOWN_MACHINES,
  MachineStatus,
} from "../../../types/factory";
import { useFactoryWebSocket } from "../../../context/WebSocketContext";

interface PipelineStageConfig {
  id: "housing" | "casting" | "assembly" | "qc";
  stepNumber: number;
  label: string;
  icon: string;
  description: string;
}

const PIPELINE_STAGES: PipelineStageConfig[] = [
  {
    id: "housing",
    stepNumber: 1,
    label: "Housing Sub-Facility",
    icon: "🏗️",
    description: "Molding and thermal forming of outer shell",
  },
  {
    id: "casting",
    stepNumber: 2,
    label: "Membrane Casting",
    icon: "🎞️",
    description: "Extrusion and solvent casting of membrane film",
  },
  {
    id: "assembly",
    stepNumber: 3,
    label: "Assembly Station",
    icon: "⚙️",
    description: "Ultrasonic welding, alignment, and seal application",
  },
  {
    id: "qc",
    stepNumber: 4,
    label: "Quality Control & Testing",
    icon: "🔬",
    description: "Automated pressure decay and leak integrity verification",
  },
];

function formatParam(key: string): { label: string; unit: string } {
  const map: Record<string, { label: string; unit: string }> = {
    mold_temperature: { label: "Mold Temperature", unit: "°C" },
    extrusion_temperature: { label: "Extrusion Temperature", unit: "°C" },
    extrusion_speed: { label: "Extrusion Speed", unit: "mm/s" },
    viscosity: { label: "Viscosity", unit: "cP" },
    humidity: { label: "Relative Humidity", unit: "%" },
    torque: { label: "Fastener Torque", unit: "N·m" },
    seal_pressure: { label: "Seal Pressure", unit: "bar" },
    decay_rate: { label: "Pressure Decay Rate", unit: "mbar/s" },
    leak_rate: { label: "Leak Rate", unit: "sccm" },
  };
  if (map[key]) return map[key];
  return {
    label: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    unit: "",
  };
}

function calculateDuration(
  entered?: string | null,
  exited?: string | null
): string | null {
  if (!entered || !exited) return null;
  const start = new Date(entered).getTime();
  const end = new Date(exited).getTime();
  if (isNaN(start) || isNaN(end) || end < start) return null;
  const sec = (end - start) / 1000;
  return `${sec.toFixed(1)}s`;
}

function UnitDetailContent() {
  const router = useRouter();
  const rawParams = useParams();
  const unitId =
    typeof rawParams?.unitId === "string"
      ? rawParams.unitId
      : Array.isArray(rawParams?.unitId)
      ? rawParams.unitId[0]
      : "";

  const { machines } = useFactoryWebSocket();

  // Find if this unit is actively on any factory floor machine right now
  const activeMachine: MachineStatus | undefined = useMemo(() => {
    if (!unitId) return undefined;
    return Object.values(machines).find(
      (m) => m.current_unit_id === unitId
    );
  }, [machines, unitId]);

  const [unit, setUnit] = useState<UnitHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const searchInput = draft ?? unitId;

  useEffect(() => {
    if (!unitId) return;
    let isMounted = true;

    fetchUnitHistory(unitId)
      .then((data) => {
        if (!isMounted) return;
        setUnit(data);
        setNotFound(false);
        setErrorMessage(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        if (err instanceof ApiError && err.status === 404) {
          if (activeMachine) {
            setUnit({
              unit_id: unitId,
              status: "in_progress",
              created_at: activeMachine.timestamp || new Date().toISOString(),
              stages: [],
              qc_result: null,
            });
            setNotFound(false);
            setErrorMessage(null);
          } else {
            setNotFound(true);
          }
        } else {
          const message = err instanceof Error ? err.message : "";
          setErrorMessage(message || "Failed to load unit history");
        }
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [unitId, activeMachine]);

  // Polling for in-progress units to auto-update when stage finishes
  useEffect(() => {
    if (!unit || unit.status !== "in_progress") return;

    const interval = setInterval(() => {
      fetchUnitHistory(unitId)
        .then((data) => {
          setUnit(data);
        })
        .catch(() => {
          // If still in-flight and 404, keep existing synthetic record
        });
    }, 3500);

    return () => clearInterval(interval);
  }, [unit, unitId]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchInput.trim()) return;
    router.push(`/units/${encodeURIComponent(searchInput.trim())}`);
    setDraft(null);
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3 font-mono">
        <div className="w-8 h-8 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin" />
        <div className="text-xs text-slate-400">
          RECONSTRUCTING TRACEABILITY TIMELINE FOR {unitId}...
        </div>
      </div>
    );
  }

  if (notFound && !activeMachine) {
    return (
      <div className="max-w-2xl mx-auto my-8 flex flex-col gap-6">
        <div className="scada-panel rounded-xl p-8 border-rose-900/60 bg-rose-950/20 text-center flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-rose-950 border border-rose-500/50 flex items-center justify-center text-rose-400 text-xl font-mono">
            !
          </div>
          <div>
            <h1 className="text-lg font-bold font-mono text-rose-300 uppercase tracking-wide">
              Unit Not Found
            </h1>
            <p className="text-sm text-slate-400 mt-1 max-w-md">
              No manufacturing history or active telemetry records exist for unit serial{" "}
              <code className="text-rose-400 font-mono font-semibold">{unitId}</code>.
            </p>
          </div>

          {/* Search box to retry */}
          <form onSubmit={handleSearchSubmit} className="flex gap-2 w-full max-w-sm mt-2">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Search serial number..."
              className="flex-1 px-3 py-2 bg-slate-950 rounded border border-slate-700 font-mono text-xs text-slate-200 focus:outline-none focus:border-cyan-400"
            />
            <button
              type="submit"
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-mono rounded border border-slate-600 cursor-pointer"
            >
              Lookup
            </button>
          </form>

          <div className="pt-4 border-t border-slate-800 w-full flex items-center justify-center gap-4 text-xs font-mono">
            <Link href="/units" className="text-cyan-400 hover:underline">
              ← Return to Units Directory
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (errorMessage && !unit && !activeMachine) {
    return (
      <div className="max-w-2xl mx-auto my-8 p-6 scada-panel rounded-xl border-amber-900/60 text-amber-300 font-mono text-xs flex flex-col gap-4">
        <div>Error loading unit: {errorMessage || "Unknown error"}</div>
        <Link href="/units" className="text-cyan-400 hover:underline">
          ← Return to Unit Directory
        </Link>
      </div>
    );
  }

  // Fallback unit representation if only active machine is known
  const displayUnit: UnitHistoryResponse = unit || {
    unit_id: unitId,
    status: "in_progress",
    created_at: activeMachine?.timestamp || new Date().toISOString(),
    stages: [],
    qc_result: null,
  };

  const qc = displayUnit.qc_result;
  const isFailed = qc?.outcome === "fail";
  const isPassed = qc?.outcome === "pass";
  const isInProgress = displayUnit.status === "in_progress";

  // Map recorded stages by sub_facility
  const stageMap = new Map<string, (typeof displayUnit.stages)[0]>();
  for (const s of displayUnit.stages) {
    stageMap.set(s.sub_facility.toLowerCase(), s);
  }

  return (
    <div className="max-w-4xl mx-auto flex flex-col gap-6">
      {/* Unit Header Card */}
      <div className="scada-panel rounded-xl p-5 border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href="/units"
            className="p-2 rounded bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700 font-mono text-xs"
            title="Back to lookup directory"
          >
            ←
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono text-slate-100 tracking-tight">
                {displayUnit.unit_id}
              </h1>
              <span
                className={`text-xs font-mono font-bold px-2 py-0.5 rounded uppercase border ${
                  isPassed
                    ? "bg-emerald-950/70 text-emerald-300 border-emerald-500/40"
                    : isFailed
                    ? "bg-rose-950/70 text-rose-300 border-rose-500/50"
                    : "bg-cyan-950/70 text-cyan-300 border-cyan-500/40 animate-pulse"
                }`}
              >
                {isInProgress ? "IN PRODUCTION" : displayUnit.status.toUpperCase()}
              </span>
            </div>
            <div className="text-xs text-slate-400 font-mono mt-1">
              Started / Registered:{" "}
              {displayUnit.created_at
                ? new Date(displayUnit.created_at).toLocaleString()
                : "Active Stream"}
            </div>
          </div>
        </div>

        {/* Search switcher */}
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Switch unit ID..."
            className="px-3 py-1.5 bg-slate-950 rounded border border-slate-700 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-400 w-44"
          />
          <button
            type="submit"
            className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-mono border border-slate-700 cursor-pointer"
          >
            Go
          </button>
        </form>
      </div>

      {/* Visual Timeline / Journey */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between px-1">
          <h2 className="text-xs font-bold font-mono uppercase tracking-wider text-slate-400">
            Manufacturing Line Journey (Stages 1 ➔ 4)
          </h2>
          <span className="text-xs font-mono text-slate-500">
            {displayUnit.stages.length} of 4 Stages Logged
          </span>
        </div>

        {/* 4-Stage Canonical Pipeline Stepper */}
        <div className="relative pl-6 md:pl-8 flex flex-col gap-6 before:content-[''] before:absolute before:left-3 md:before:left-4 before:top-4 before:bottom-4 before:w-[2px] before:bg-slate-800">
          {PIPELINE_STAGES.map((stageConfig, stageIndex) => {
            const recordedStage = stageMap.get(stageConfig.id);
            const isCurrentlyOnMachine =
              activeMachine &&
              activeMachine.sub_facility.toLowerCase() === stageConfig.id;

            // Determine if previous stage completed
            const prevStageCompleted =
              stageIndex === 0 ||
              Boolean(stageMap.get(PIPELINE_STAGES[stageIndex - 1].id));

            const isAttributedRootCause =
              isFailed &&
              qc?.attributed_stage?.toLowerCase() === stageConfig.id;

            // Determine state of this stage
            let stageState: "completed" | "in_flight" | "queued" | "pending" = "pending";
            if (stageConfig.id === "qc" && qc) {
              stageState = "completed";
            } else if (recordedStage) {
              stageState = "completed";
            } else if (isCurrentlyOnMachine) {
              stageState = "in_flight";
            } else if (prevStageCompleted) {
              stageState = "queued";
            }

            const machineId = recordedStage
              ? recordedStage.machine_id
              : isCurrentlyOnMachine
              ? activeMachine.machine_id
              : null;
            const machineMeta = machineId ? KNOWN_MACHINES[machineId] : null;
            const machineName = machineMeta?.name || machineId;

            const isHighAnomaly =
              recordedStage && recordedStage.anomaly_score > 2.0;
            const durationStr = recordedStage
              ? calculateDuration(recordedStage.entered_at, recordedStage.exited_at)
              : null;

            return (
              <div
                key={stageConfig.id}
                className={`relative scada-panel rounded-xl p-4 lg:p-5 border transition-all ${
                  isAttributedRootCause
                    ? "border-rose-600/80 bg-rose-950/20 shadow-[0_0_25px_rgba(225,29,72,0.25)]"
                    : stageState === "in_flight"
                    ? "border-cyan-500/60 bg-cyan-950/20 shadow-[0_0_20px_rgba(6,182,212,0.2)]"
                    : stageState === "completed"
                    ? isHighAnomaly
                      ? "border-amber-500/50 bg-slate-900/60"
                      : "border-slate-800"
                    : stageState === "queued"
                    ? "border-amber-500/30 bg-amber-950/10"
                    : "border-slate-800/40 opacity-70 bg-slate-950/40"
                }`}
              >
                {/* Timeline Step Dot */}
                <div
                  className={`absolute -left-[31px] md:-left-[39px] top-5 w-6 h-6 rounded-full border-2 flex items-center justify-center text-[10px] font-mono font-bold ${
                    isAttributedRootCause
                      ? "bg-rose-950 border-rose-500 text-rose-300 animate-pulse"
                      : stageState === "in_flight"
                      ? "bg-cyan-950 border-cyan-400 text-cyan-300 animate-pulse"
                      : stageState === "completed"
                      ? isHighAnomaly
                        ? "bg-amber-950 border-amber-500 text-amber-300"
                        : "bg-slate-950 border-cyan-500 text-cyan-300"
                      : stageState === "queued"
                      ? "bg-slate-950 border-amber-500 text-amber-400"
                      : "bg-slate-950 border-slate-700 text-slate-500"
                  }`}
                >
                  {stageConfig.stepNumber}
                </div>

                {/* Stage Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className="text-lg p-1.5 rounded bg-slate-900 border border-slate-800">
                      {stageConfig.icon}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-bold font-mono text-slate-100 uppercase">
                          {stageConfig.label}
                        </h3>
                        {machineName && (
                          <span className="text-xs font-mono text-cyan-400 font-medium">
                            ({machineName})
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-400">
                        {stageConfig.description}
                      </p>
                    </div>
                  </div>

                  {/* Stage Status Pill */}
                  <div className="flex items-center gap-2 font-mono text-xs">
                    {isAttributedRootCause && (
                      <span className="px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-500/70 font-bold uppercase animate-pulse">
                        ⚠️ Root Cause Stage
                      </span>
                    )}

                    {stageState === "completed" && (
                      <span
                        className={`px-2 py-0.5 rounded uppercase border font-semibold ${
                          stageConfig.id === "qc" && isFailed
                            ? "bg-rose-950/60 text-rose-400 border-rose-500/40"
                            : "bg-emerald-950/60 text-emerald-400 border-emerald-500/30"
                        }`}
                      >
                        {stageConfig.id === "qc"
                          ? qc?.outcome?.toUpperCase() || "COMPLETED"
                          : recordedStage?.outcome || "COMPLETED"}
                      </span>
                    )}

                    {stageState === "in_flight" && (
                      <span className="px-2 py-0.5 rounded uppercase border font-semibold bg-cyan-950/70 text-cyan-300 border-cyan-500/50 flex items-center gap-1.5 animate-pulse">
                        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                        PROCESSING NOW
                      </span>
                    )}

                    {stageState === "queued" && (
                      <span className="px-2 py-0.5 rounded uppercase border font-semibold bg-amber-950/60 text-amber-300 border-amber-500/40 flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                        QUEUED IN BUFFER
                      </span>
                    )}

                    {stageState === "pending" && (
                      <span className="px-2 py-0.5 rounded uppercase border font-semibold bg-slate-900 text-slate-500 border-slate-800">
                        PENDING UPSTREAM
                      </span>
                    )}
                  </div>
                </div>

                {/* Render Completed Stage Details */}
                {stageState === "completed" && recordedStage && (
                  <>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 my-3 p-2.5 rounded bg-slate-950/70 border border-slate-800/80 text-xs font-mono">
                      <div>
                        <span className="text-slate-500 text-[10px] block uppercase">
                          Entered Station
                        </span>
                        <span className="text-slate-300">
                          {recordedStage.entered_at
                            ? new Date(recordedStage.entered_at).toLocaleTimeString()
                            : "--"}
                        </span>
                      </div>

                      <div>
                        <span className="text-slate-500 text-[10px] block uppercase">
                          Exited Station (Duration)
                        </span>
                        <span className="text-slate-300">
                          {recordedStage.exited_at
                            ? new Date(recordedStage.exited_at).toLocaleTimeString()
                            : "--"}
                          {durationStr && (
                            <span className="text-cyan-400 ml-1.5 font-semibold">
                              ({durationStr})
                            </span>
                          )}
                        </span>
                      </div>

                      <div>
                        <div className="flex items-center justify-between">
                          <span className="text-slate-500 text-[10px] uppercase">
                            Anomaly Score
                          </span>
                          {isHighAnomaly && (
                            <span className="text-[9px] px-1 py-0.2 rounded bg-amber-950 text-amber-400 border border-amber-500/40 font-bold">
                              WARNING &gt; 2.0
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span
                            className={`text-sm font-bold ${
                              isHighAnomaly ? "text-amber-400" : "text-emerald-400"
                            }`}
                          >
                            {recordedStage.anomaly_score.toFixed(3)}
                          </span>
                          <div className="h-1.5 flex-1 bg-slate-900 rounded-full overflow-hidden border border-slate-800">
                            <div
                              className={`h-full ${
                                isHighAnomaly ? "bg-amber-400" : "bg-emerald-400"
                              }`}
                              style={{
                                width: `${Math.min(
                                  100,
                                  (recordedStage.anomaly_score / 4.0) * 100
                                )}%`,
                              }}
                            />
                          </div>
                        </div>
                      </div>
                    </div>

                    <div>
                      <div className="text-[10px] font-mono text-slate-500 uppercase tracking-wider mb-2">
                        Process Sensor Readings At Moment of Completion
                      </div>
                      {recordedStage.readings &&
                      Object.keys(recordedStage.readings).length > 0 ? (
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                          {Object.entries(recordedStage.readings).map(
                            ([key, val]) => {
                              const { label, unit } = formatParam(key);
                              const isNum = typeof val === "number";
                              return (
                                <div
                                  key={key}
                                  className="bg-slate-900/80 border border-slate-800 rounded p-2 flex flex-col justify-between"
                                >
                                  <span className="text-[10px] text-slate-400 truncate">
                                    {label}
                                  </span>
                                  <span className="font-mono text-xs font-semibold text-slate-200 mt-1">
                                    {isNum ? Number(val).toFixed(2) : String(val)}
                                    {unit && (
                                      <span className="text-slate-500 ml-0.5">
                                        {unit}
                                      </span>
                                    )}
                                  </span>
                                </div>
                              );
                            }
                          )}
                        </div>
                      ) : (
                        <div className="text-xs text-slate-500 italic font-mono">
                          No snapshot sensor data recorded.
                        </div>
                      )}
                    </div>
                  </>
                )}

                {/* Render In-Flight Live State */}
                {stageState === "in_flight" && activeMachine && (
                  <div className="mt-3 p-3.5 rounded-lg bg-cyan-950/30 border border-cyan-500/40 flex flex-col gap-3">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs font-mono gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-cyan-300 font-bold">
                          Station: {machineName}
                        </span>
                        {activeMachine.phase && (
                          <span className="px-2 py-0.5 rounded bg-cyan-900/60 text-cyan-200 border border-cyan-500/50 font-bold uppercase text-[10px]">
                            Phase: {activeMachine.phase}
                          </span>
                        )}
                      </div>
                      <span className="text-slate-400 text-[11px]">
                        State:{" "}
                        <strong
                          className={
                            activeMachine.starved
                              ? "text-amber-400"
                              : "text-emerald-400"
                          }
                        >
                          {activeMachine.starved ? "STARVED" : activeMachine.machine_state}
                        </strong>
                      </span>
                    </div>

                    {/* Live sensor readings from machine */}
                    {activeMachine.extra &&
                      Object.keys(activeMachine.extra).length > 0 && (
                        <div>
                          <div className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider mb-2">
                            Live Telemetry Readings (Streaming from Station Bus)
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            {Object.entries(activeMachine.extra).map(
                              ([key, val]) => {
                                const { label, unit } = formatParam(key);
                                const isNum = typeof val === "number";
                                return (
                                  <div
                                    key={key}
                                    className="bg-slate-900/90 border border-cyan-900/60 rounded p-2 flex flex-col justify-between"
                                  >
                                    <span className="text-[10px] text-slate-400 truncate">
                                      {label}
                                    </span>
                                    <span className="font-mono text-xs font-semibold text-cyan-300 mt-1">
                                      {isNum
                                        ? Number(val).toFixed(2)
                                        : String(val)}
                                      {unit && (
                                        <span className="text-slate-500 ml-0.5">
                                          {unit}
                                        </span>
                                      )}
                                    </span>
                                  </div>
                                );
                              }
                            )}
                          </div>
                        </div>
                      )}
                  </div>
                )}

                {/* Render Queued State */}
                {stageState === "queued" && (
                  <div className="my-2 p-3 rounded bg-amber-950/20 border border-dashed border-amber-500/30 text-xs font-mono text-amber-300 flex items-center justify-between">
                    <span>
                      ⏳ Unit is buffered in transfer queue, awaiting pickup by next available station.
                    </span>
                    <span className="text-[10px] text-slate-500">
                      Buffer Queue Wait
                    </span>
                  </div>
                )}

                {/* Render Pending State */}
                {stageState === "pending" && (
                  <div className="my-2 p-2.5 text-xs font-mono text-slate-500 italic">
                    Awaiting completion of upstream manufacturing stages.
                  </div>
                )}

                {/* Special Section for Stage 4: QC Verdict */}
                {stageConfig.id === "qc" && qc && (
                  <div className="mt-4 pt-4 border-t border-slate-800 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-lg font-bold font-mono ${
                            isPassed ? "text-emerald-400" : "text-rose-400"
                          }`}
                        >
                          {isPassed ? "✓ QC INSPECTION PASSED" : "✗ QC INSPECTION FAILED"}
                        </span>
                      </div>
                      <span className="text-xs font-mono text-slate-400">
                        {qc.tested_at ? new Date(qc.tested_at).toLocaleTimeString() : ""}
                      </span>
                    </div>

                    {isFailed && (
                      <div className="p-4 rounded-lg bg-rose-950/50 border border-rose-500/60 flex flex-col gap-3">
                        <div className="flex items-center justify-between">
                          <div className="text-rose-400 font-mono font-bold text-sm flex items-center gap-2">
                            <span>UNIT FLAGGED FOR DEFECT</span>
                          </div>
                          <div className="font-mono text-xs text-rose-300">
                            P(defect) = {(qc.probability * 100).toFixed(1)}%
                          </div>
                        </div>

                        {/* Operator Diagnostic Statement (as explicitly required) */}
                        <div className="p-3 rounded bg-slate-950 border border-rose-900 text-xs font-mono text-rose-200">
                          <div className="text-slate-400 text-[10px] uppercase font-bold tracking-wider mb-1">
                            QC Diagnostics Summary:
                          </div>
                          <p className="leading-relaxed">
                            This unit failed due to{" "}
                            <strong className="text-rose-400 underline underline-offset-2">
                              {qc.defect_type || "DETECTED_ANOMALY"}
                            </strong>
                            , most likely caused by anomalous readings at the{" "}
                            <strong className="text-amber-300 underline underline-offset-2">
                              {qc.attributed_stage || "upstream"}
                            </strong>{" "}
                            stage.
                          </p>
                        </div>

                        <div className="grid grid-cols-2 gap-3 text-xs font-mono pt-1">
                          <div>
                            <span className="text-slate-400 text-[10px] block uppercase">
                              Identified Defect Type
                            </span>
                            <span className="text-rose-300 font-bold">
                              {qc.defect_type}
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-400 text-[10px] block uppercase">
                              Root Cause Stage Attribution
                            </span>
                            <span className="text-amber-300 font-bold uppercase">
                              {qc.attributed_stage}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function UnitDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3 font-mono">
          <div className="w-8 h-8 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin" />
          <div className="text-xs text-slate-400">
            LOADING TRACEABILITY MODULE...
          </div>
        </div>
      }
    >
      <UnitDetailContent />
    </Suspense>
  );
}
