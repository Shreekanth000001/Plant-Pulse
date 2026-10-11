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
          // If still in-flight, keep existing record
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
        <div className="w-8 h-8 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
        <div className="text-xs text-slate-600 font-medium">
          Reconstructing traceability genealogy for {unitId}...
        </div>
      </div>
    );
  }

  if (notFound && !activeMachine) {
    return (
      <div className="max-w-2xl mx-auto my-8 flex flex-col gap-6">
        <div className="bg-white rounded-3xl p-8 md:p-10 border-2 border-rose-300 text-center flex flex-col items-center gap-4 shadow-sm">
          <div className="w-14 h-14 rounded-2xl bg-rose-50 border-2 border-rose-200 flex items-center justify-center text-rose-700 text-2xl font-bold">
            !
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">
              Unit Not Found
            </h1>
            <p className="text-xs md:text-sm text-slate-600 mt-1 max-w-md font-medium">
              No manufacturing history or active floor telemetry records exist for serial{" "}
              <code className="text-rose-700 font-mono font-bold bg-rose-50 px-1.5 py-0.5 rounded border border-rose-200">{unitId}</code>.
            </p>
          </div>

          {/* Search box to retry */}
          <form onSubmit={handleSearchSubmit} className="flex gap-2 w-full max-w-sm mt-3">
            <label htmlFor="notfound-unit-search" className="sr-only">
              Search Unit Serial Number
            </label>
            <input
              id="notfound-unit-search"
              type="text"
              value={searchInput}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Search serial number..."
              className="flex-1 px-4 py-2.5 bg-white rounded-xl border-2 border-slate-300 font-mono text-xs text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 shadow-xs"
            />
            <button
              type="submit"
              className="px-5 py-2.5 bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold rounded-xl transition-colors cursor-pointer shadow-xs"
            >
              Lookup
            </button>
          </form>

          <div className="pt-4 border-t border-slate-200 w-full flex items-center justify-center gap-4 text-xs">
            <Link href="/units" className="text-blue-600 hover:underline font-bold">
              ← Return to Units Directory
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (errorMessage && !unit && !activeMachine) {
    return (
      <div className="max-w-2xl mx-auto my-8 p-6 bg-white rounded-3xl border-2 border-amber-300 text-amber-950 text-xs flex flex-col gap-4 shadow-sm font-medium">
        <div>Error loading unit: {errorMessage || "Unknown error"}</div>
        <Link href="/units" className="text-blue-600 hover:underline font-bold">
          ← Return to Units Directory
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
      <div className="bg-white rounded-3xl p-6 border border-slate-300 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
        <div className="flex items-center gap-4">
          <Link
            href="/units"
            className="w-10 h-10 rounded-xl bg-slate-100 border border-slate-300 text-slate-700 hover:text-slate-900 hover:bg-slate-200 flex items-center justify-center text-sm font-bold transition-all shadow-2xs"
            title="Back to lookup directory"
          >
            ←
          </Link>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl md:text-2xl font-bold font-mono text-slate-900 tracking-tight">
                {displayUnit.unit_id}
              </h1>
              <span
                className={`text-xs font-bold px-3 py-1 rounded-full border capitalize ${
                  isPassed
                    ? "bg-emerald-50 text-emerald-800 border-emerald-300"
                    : isFailed
                    ? "bg-rose-50 text-rose-800 border-rose-300"
                    : "bg-blue-50 text-blue-800 border-blue-300 animate-pulse"
                }`}
              >
                {isInProgress ? "In Production" : displayUnit.status}
              </span>
            </div>
            <div className="text-xs text-slate-600 font-medium mt-1">
              Started / Registered:{" "}
              <strong className="text-slate-800">
                {displayUnit.created_at
                  ? new Date(displayUnit.created_at).toLocaleString()
                  : "Active floor stream"}
              </strong>
            </div>

            {isInProgress && (
              <div className="flex items-center gap-1.5 text-[11px] text-blue-700 font-mono mt-1.5 bg-blue-50/80 border border-blue-200/80 px-2.5 py-0.5 rounded-full w-fit">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />
                <span>Live floor polling active (updates every 3.5s)</span>
              </div>
            )}
          </div>
        </div>

        {/* Quick serial switcher */}
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
          <label htmlFor="quick-unit-search" className="sr-only">
            Switch Unit Serial ID
          </label>
          <input
            id="quick-unit-search"
            type="text"
            value={searchInput}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Switch unit ID..."
            className="px-3.5 py-2 bg-white rounded-xl border-2 border-slate-300 text-xs font-mono text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 w-44 shadow-2xs"
          />
          <button
            type="submit"
            className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold transition-colors cursor-pointer shadow-xs"
          >
            Go
          </button>
        </form>
      </div>

      {/* Visual Timeline / Journey */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between px-1">
          <h2 className="text-sm font-bold text-slate-900 tracking-tight">
            Manufacturing Line Journey (Stages 1 ➔ 4)
          </h2>
          <span className="text-xs text-slate-700 font-semibold">
            {displayUnit.stages.length} of 4 Stages Logged
          </span>
        </div>

        {/* 4-Stage Canonical Pipeline Stepper */}
        <div className="relative pl-7 md:pl-9 flex flex-col gap-6 before:content-[''] before:absolute before:left-3.5 md:before:left-4 before:top-5 before:bottom-5 before:w-[3px] before:bg-slate-300">
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
                className={`relative rounded-2xl p-5 lg:p-6 border-2 transition-all duration-300 ${
                  isAttributedRootCause
                    ? "border-rose-400 bg-rose-50/70 shadow-sm ring-2 ring-rose-200"
                    : stageState === "in_flight"
                    ? "border-blue-400 bg-blue-50/60 shadow-sm ring-2 ring-blue-200"
                    : stageState === "completed"
                    ? isHighAnomaly
                      ? "border-amber-400 bg-amber-50/50 shadow-sm"
                      : "border-slate-300 bg-white shadow-xs"
                    : stageState === "queued"
                    ? "border-amber-300 bg-amber-50/40"
                    : "border-slate-200 bg-slate-50/80 opacity-80"
                }`}
              >
                {/* Timeline Step Dot */}
                <div
                  className={`absolute -left-[35px] md:-left-[43px] top-6 w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold shadow-xs ${
                    isAttributedRootCause
                      ? "bg-rose-100 border-rose-500 text-rose-800 animate-pulse"
                      : stageState === "in_flight"
                      ? "bg-blue-100 border-blue-600 text-blue-800 animate-pulse"
                      : stageState === "completed"
                      ? isHighAnomaly
                        ? "bg-amber-100 border-amber-500 text-amber-900"
                        : "bg-emerald-100 border-emerald-600 text-emerald-800"
                      : stageState === "queued"
                      ? "bg-amber-50 border-amber-400 text-amber-800"
                      : "bg-slate-100 border-slate-400 text-slate-600"
                  }`}
                >
                  {stageConfig.stepNumber}
                </div>

                {/* Stage Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3.5 border-b border-slate-200 gap-2">
                  <div className="flex items-center gap-3">
                    <span className="text-xl p-2 rounded-xl bg-slate-100 border border-slate-300 shadow-2xs">
                      {stageConfig.icon}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-bold text-slate-900">
                          {stageConfig.label}
                        </h3>
                        {machineName && (
                          <span className="text-xs font-mono text-blue-700 font-bold">
                            ({machineName})
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-600 font-medium mt-0.5">
                        {stageConfig.description}
                      </p>
                    </div>
                  </div>

                  {/* Stage Status Pill */}
                  <div className="flex items-center gap-2 text-xs">
                    {isAttributedRootCause && (
                      <span className="px-3 py-1 rounded-full bg-rose-100 text-rose-800 border border-rose-300 font-bold uppercase animate-pulse">
                        ⚠️ Root Cause Stage
                      </span>
                    )}

                    {stageState === "completed" && (
                      <span
                        className={`px-3 py-1 rounded-full border text-xs font-bold capitalize ${
                          stageConfig.id === "qc" && isFailed
                            ? "bg-rose-100 text-rose-800 border-rose-300"
                            : "bg-emerald-50 text-emerald-800 border-emerald-300"
                        }`}
                      >
                        {stageConfig.id === "qc"
                          ? qc?.outcome || "Completed"
                          : recordedStage?.outcome || "Completed"}
                      </span>
                    )}

                    {stageState === "in_flight" && (
                      <span className="px-3 py-1 rounded-full border border-blue-300 text-xs font-bold bg-blue-50 text-blue-800 flex items-center gap-1.5 animate-pulse">
                        <span className="w-1.5 h-1.5 rounded-full bg-blue-600" />
                        Processing Now
                      </span>
                    )}

                    {stageState === "queued" && (
                      <span className="px-3 py-1 rounded-full border border-amber-300 text-xs font-bold bg-amber-50 text-amber-900 flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                        Queued in Buffer
                      </span>
                    )}

                    {stageState === "pending" && (
                      <span className="px-3 py-1 rounded-full border border-slate-300 text-xs font-semibold bg-slate-100 text-slate-600">
                        Pending Upstream
                      </span>
                    )}
                  </div>
                </div>

                {/* Render Completed Stage Details */}
                {stageState === "completed" && recordedStage && (
                  <>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 my-3 p-3 rounded-xl bg-slate-50 border border-slate-200 text-xs">
                      <div>
                        <span className="text-slate-600 text-[10px] block font-bold uppercase tracking-wider">
                          Entered Station
                        </span>
                        <span className="text-slate-900 font-mono font-bold mt-0.5 block">
                          {recordedStage.entered_at
                            ? new Date(recordedStage.entered_at).toLocaleTimeString()
                            : "--"}
                        </span>
                      </div>

                      <div>
                        <span className="text-slate-600 text-[10px] block font-bold uppercase tracking-wider">
                          Exited Station (Duration)
                        </span>
                        <span className="text-slate-900 font-mono font-bold mt-0.5 block">
                          {recordedStage.exited_at
                            ? new Date(recordedStage.exited_at).toLocaleTimeString()
                            : "--"}
                          {durationStr && (
                            <span className="text-blue-700 ml-1.5 font-bold">
                              ({durationStr})
                            </span>
                          )}
                        </span>
                      </div>

                      <div>
                        <div className="flex items-center justify-between">
                          <span className="text-slate-600 text-[10px] font-bold uppercase tracking-wider">
                            Anomaly Score
                          </span>
                          {isHighAnomaly && (
                            <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-amber-100 text-amber-900 border border-amber-300 font-bold">
                              Warning &gt; 2.0
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          <span
                            className={`font-mono text-sm font-bold ${
                              isHighAnomaly ? "text-amber-900" : "text-emerald-800"
                            }`}
                          >
                            {recordedStage.anomaly_score.toFixed(3)}
                          </span>
                          <div className="h-2 flex-1 bg-slate-200 rounded-full overflow-hidden border border-slate-300/60">
                            <div
                              className={`h-full rounded-full ${
                                isHighAnomaly ? "bg-amber-500" : "bg-emerald-600"
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
                      <div className="text-xs font-bold text-slate-800 mb-2">
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
                                  className="bg-slate-50 border border-slate-300 rounded-xl p-2.5 flex flex-col justify-between shadow-2xs"
                                >
                                  <span className="text-[11px] text-slate-700 truncate font-semibold">
                                    {label}
                                  </span>
                                  <span className="font-mono text-xs font-bold text-slate-900 mt-1">
                                    {isNum ? Number(val).toFixed(2) : String(val)}
                                    {unit && (
                                      <span className="text-slate-600 font-semibold ml-0.5">
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
                        <div className="text-xs text-slate-500 italic">
                          No snapshot sensor data recorded.
                        </div>
                      )}
                    </div>
                  </>
                )}

                {/* Render In-Flight Live State */}
                {stageState === "in_flight" && activeMachine && (
                  <div className="mt-3 p-4 rounded-xl bg-blue-50 border-2 border-blue-300 flex flex-col gap-3">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-blue-950 font-bold">
                          Station: {machineName}
                        </span>
                        {activeMachine.phase && (
                          <span className="px-2.5 py-0.5 rounded-full bg-white text-blue-800 border border-blue-300 font-bold text-[11px] capitalize">
                            Phase: {activeMachine.phase.toLowerCase()}
                          </span>
                        )}
                      </div>
                      <span className="text-slate-700 font-medium">
                        Operating State:{" "}
                        <strong
                          className={
                            activeMachine.starved
                              ? "text-amber-900 font-bold"
                              : "text-emerald-800 font-bold"
                          }
                        >
                          {activeMachine.starved ? "Starved" : activeMachine.machine_state}
                        </strong>
                      </span>
                    </div>

                    {/* Live sensor readings from machine */}
                    {activeMachine.extra &&
                      Object.keys(activeMachine.extra).length > 0 && (
                        <div>
                          <div className="text-xs font-bold text-blue-950 mb-2">
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
                                    className="bg-white border border-blue-300 rounded-xl p-2.5 flex flex-col justify-between shadow-2xs"
                                  >
                                    <span className="text-[11px] text-slate-700 truncate font-semibold">
                                      {label}
                                    </span>
                                    <span className="font-mono text-xs font-bold text-slate-900 mt-1">
                                      {isNum
                                        ? Number(val).toFixed(2)
                                        : String(val)}
                                      {unit && (
                                        <span className="text-slate-600 font-semibold ml-0.5">
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
                  <div className="my-2 p-3.5 rounded-xl bg-amber-50 border-2 border-amber-300 text-xs text-amber-950 flex items-center justify-between font-semibold">
                    <span>
                      ⏳ Unit is buffered in transfer queue, awaiting pickup by next available station.
                    </span>
                    <span className="text-xs text-slate-600 font-bold">
                      Buffer Queue
                    </span>
                  </div>
                )}

                {/* Render Pending State */}
                {stageState === "pending" && (
                  <div className="my-2 p-2.5 text-xs text-slate-500 font-medium italic">
                    Awaiting completion of upstream manufacturing stages.
                  </div>
                )}

                {/* Special Section for Stage 4: QC Verdict */}
                {stageConfig.id === "qc" && qc && (
                  <div className="mt-4 pt-4 border-t border-slate-200 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-base font-bold ${
                            isPassed ? "text-emerald-800" : "text-rose-800"
                          }`}
                        >
                          {isPassed ? "✓ QC Inspection Passed" : "✗ QC Inspection Flagged"}
                        </span>
                      </div>
                      <span className="text-xs text-slate-600 font-medium">
                        {qc.tested_at ? new Date(qc.tested_at).toLocaleTimeString() : ""}
                      </span>
                    </div>

                    {isFailed && (
                      <div className="p-4.5 rounded-2xl bg-rose-50 border-2 border-rose-300 flex flex-col gap-3.5">
                        <div className="flex items-center justify-between">
                          <div className="text-rose-900 font-bold text-sm">
                            Unit Flagged for Defect
                          </div>
                          <div className="font-mono text-xs text-rose-800 font-bold">
                            P(defect) = {(qc.probability * 100).toFixed(1)}%
                          </div>
                        </div>

                        {/* Operator Diagnostic Statement (as explicitly required) */}
                        <div className="p-3.5 rounded-xl bg-white border-2 border-rose-300 text-xs text-slate-900 shadow-2xs">
                          <div className="text-slate-600 text-[10px] uppercase font-bold tracking-wider mb-1">
                            QC Diagnostics Summary:
                          </div>
                          <p className="leading-relaxed font-medium">
                            This unit failed due to{" "}
                            <strong className="text-rose-800 font-bold underline underline-offset-2">
                              {qc.defect_type || "DETECTED_ANOMALY"}
                            </strong>
                            , most likely caused by anomalous readings at the{" "}
                            <strong className="text-amber-900 font-bold underline underline-offset-2">
                              {qc.attributed_stage || "upstream"}
                            </strong>{" "}
                            stage.
                          </p>
                        </div>

                        <div className="grid grid-cols-2 gap-3 text-xs pt-1">
                          <div>
                            <span className="text-slate-600 text-[11px] block font-bold">
                              Identified Defect Type
                            </span>
                            <span className="text-rose-800 font-bold font-mono mt-0.5 block">
                              {qc.defect_type}
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-600 text-[11px] block font-bold">
                              Root Cause Stage Attribution
                            </span>
                            <span className="text-amber-900 font-bold uppercase font-mono mt-0.5 block">
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
          <div className="w-8 h-8 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
          <div className="text-xs text-slate-600 font-medium">
            Loading traceability module...
          </div>
        </div>
      }
    >
      <UnitDetailContent />
    </Suspense>
  );
}
