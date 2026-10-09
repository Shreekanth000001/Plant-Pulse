"use client";

import React, { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useParams } from "next/navigation";
import { fetchUnitHistory, ApiError } from "../../../lib/api";
import { UnitHistoryResponse, KNOWN_MACHINES } from "../../../types/factory";

const STAGE_METADATA: Record<
  string,
  { label: string; icon: string; description: string }
> = {
  housing: {
    label: "Housing Sub-Facility",
    icon: "🏗️",
    description: "Molding and thermal forming of outer shell",
  },
  casting: {
    label: "Membrane Casting",
    icon: "🎞️",
    description: "Extrusion and solvent casting of membrane film",
  },
  assembly: {
    label: "Assembly Station",
    icon: "⚙️",
    description: "Ultrasonic welding, alignment, and seal application",
  },
  qc: {
    label: "Quality Control",
    icon: "🔬",
    description: "Automated optical, pressure decay and leak testing",
  },
};

function formatParam(key: string): { label: string; unit: string } {
  const map: Record<string, { label: string; unit: string }> = {
    mold_temperature: { label: "Mold Temperature", unit: "°C" },
    extrusion_temperature: { label: "Extrusion Temperature", unit: "°C" },
    extrusion_speed: { label: "Extrusion Speed", unit: "mm/s" },
    viscosity: { label: "Viscosity", unit: "cP" },
    humidity: { label: "Relative Humidity", unit: "%" },
    torque: { label: "Fastener Torque", unit: "N·m" },
    seal_pressure: { label: "Seal Pressure", unit: "bar" },
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

  const [unit, setUnit] = useState<UnitHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState(unitId);

  useEffect(() => {
    if (!unitId) return;
    setSearchInput(unitId);
    let isMounted = true;

    async function loadData() {
      try {
        setLoading(true);
        setNotFound(false);
        setErrorMessage(null);
        const data = await fetchUnitHistory(unitId);
        if (!isMounted) return;
        setUnit(data);
        setLoading(false);
      } catch (err: any) {
        if (!isMounted) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setErrorMessage(err.message || "Failed to load unit history");
        }
        setLoading(false);
      }
    }

    loadData();
    return () => {
      isMounted = false;
    };
  }, [unitId]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchInput.trim()) return;
    router.push(`/units/${encodeURIComponent(searchInput.trim())}`);
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

  if (notFound) {
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
              No manufacturing history or telemetry records exist for unit serial{" "}
              <code className="text-rose-400 font-mono font-semibold">{unitId}</code>.
            </p>
          </div>

          {/* Search box to retry */}
          <form onSubmit={handleSearchSubmit} className="flex gap-2 w-full max-w-sm mt-2">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Try unit_000001..."
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
            <span className="text-slate-500">Try known units:</span>
            <Link href="/units/unit_000001" className="text-cyan-400 hover:underline">
              unit_000001
            </Link>
            <Link href="/units/unit_000002" className="text-cyan-400 hover:underline">
              unit_000002
            </Link>
            <Link href="/units/unit_000003" className="text-cyan-400 hover:underline">
              unit_000003
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (errorMessage || !unit) {
    return (
      <div className="max-w-2xl mx-auto my-8 p-6 scada-panel rounded-xl border-amber-900/60 text-amber-300 font-mono text-xs flex flex-col gap-4">
        <div>Error loading unit: {errorMessage || "Unknown error"}</div>
        <Link href="/units" className="text-cyan-400 hover:underline">
          ← Return to Unit Directory
        </Link>
      </div>
    );
  }

  const qc = unit.qc_result;
  const isFailed = qc?.outcome === "fail";
  const isPassed = qc?.outcome === "pass";

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
                {unit.unit_id}
              </h1>
              <span
                className={`text-xs font-mono font-bold px-2 py-0.5 rounded uppercase border ${
                  isPassed
                    ? "bg-emerald-950/70 text-emerald-300 border-emerald-500/40"
                    : isFailed
                    ? "bg-rose-950/70 text-rose-300 border-rose-500/50"
                    : "bg-amber-950/70 text-amber-300 border-amber-500/40"
                }`}
              >
                {unit.status.toUpperCase()}
              </span>
            </div>
            <div className="text-xs text-slate-400 font-mono mt-1">
              Manufactured: {unit.created_at ? new Date(unit.created_at).toLocaleString() : "Unknown"}
            </div>
          </div>
        </div>

        {/* Search switcher */}
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Switch unit ID..."
            className="px-3 py-1.5 bg-slate-950 rounded border border-slate-700 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-400 w-40"
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
            Manufacturing Journey (Stages 1 ➔ 4)
          </h2>
          <span className="text-xs font-mono text-slate-500">
            {unit.stages.length} Stage Records Registered
          </span>
        </div>

        {/* Timeline Sequence */}
        <div className="relative pl-6 md:pl-8 flex flex-col gap-6 before:content-[''] before:absolute before:left-3 md:before:left-4 before:top-4 before:bottom-4 before:w-[2px] before:bg-slate-800">
          {unit.stages.map((stage, index) => {
            const meta = STAGE_METADATA[stage.sub_facility] || {
              label: stage.sub_facility,
              icon: "📦",
              description: "Factory processing stage",
            };
            const machineMeta = KNOWN_MACHINES[stage.machine_id];
            const machineName = machineMeta?.name || stage.machine_id;

            const isHighAnomaly = stage.anomaly_score > 2.0;
            const isAttributedRootCause =
              isFailed && qc?.attributed_stage?.toLowerCase() === stage.sub_facility.toLowerCase();

            const durationStr = calculateDuration(stage.entered_at, stage.exited_at);

            return (
              <div
                key={`${stage.sub_facility}-${index}`}
                className={`relative scada-panel rounded-xl p-4 lg:p-5 border transition-all ${
                  isAttributedRootCause
                    ? "border-rose-600/80 bg-rose-950/20 shadow-[0_0_25px_rgba(225,29,72,0.25)]"
                    : isHighAnomaly
                    ? "border-amber-500/50 bg-slate-900/60"
                    : "border-slate-800"
                }`}
              >
                {/* Timeline Step Dot */}
                <div
                  className={`absolute -left-[31px] md:-left-[39px] top-5 w-6 h-6 rounded-full border-2 flex items-center justify-center text-[10px] font-mono font-bold ${
                    isAttributedRootCause
                      ? "bg-rose-950 border-rose-500 text-rose-300 animate-pulse"
                      : isHighAnomaly
                      ? "bg-amber-950 border-amber-500 text-amber-300"
                      : "bg-slate-950 border-cyan-500 text-cyan-300"
                  }`}
                >
                  {index + 1}
                </div>

                {/* Stage Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className="text-lg p-1.5 rounded bg-slate-900 border border-slate-800">
                      {meta.icon}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-bold font-mono text-slate-100 uppercase">
                          {meta.label}
                        </h3>
                        <span className="text-xs font-mono text-cyan-400 font-medium">
                          ({machineName})
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400">{meta.description}</p>
                    </div>
                  </div>

                  {/* Stage Outcome & Root Cause Banner */}
                  <div className="flex items-center gap-2 font-mono text-xs">
                    {isAttributedRootCause && (
                      <span className="px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-500/70 font-bold uppercase animate-pulse">
                        ⚠️ Root Cause Stage
                      </span>
                    )}

                    <span
                      className={`px-2 py-0.5 rounded uppercase border font-semibold ${
                        stage.outcome === "ok"
                          ? "bg-emerald-950/60 text-emerald-400 border-emerald-500/30"
                          : "bg-amber-950/60 text-amber-400 border-amber-500/40"
                      }`}
                    >
                      {stage.outcome}
                    </span>
                  </div>
                </div>

                {/* Processing Metadata: Timestamps & Anomaly Score */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 my-3 p-2.5 rounded bg-slate-950/70 border border-slate-800/80 text-xs font-mono">
                  <div>
                    <span className="text-slate-500 text-[10px] block uppercase">
                      Entered Station
                    </span>
                    <span className="text-slate-300">
                      {stage.entered_at ? new Date(stage.entered_at).toLocaleTimeString() : "--"}
                    </span>
                  </div>

                  <div>
                    <span className="text-slate-500 text-[10px] block uppercase">
                      Exited Station (Duration)
                    </span>
                    <span className="text-slate-300">
                      {stage.exited_at ? new Date(stage.exited_at).toLocaleTimeString() : "--"}
                      {durationStr && <span className="text-cyan-400 ml-1.5 font-semibold">({durationStr})</span>}
                    </span>
                  </div>

                  {/* Anomaly Score */}
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
                        {stage.anomaly_score.toFixed(3)}
                      </span>
                      {/* Mini visual meter */}
                      <div className="h-1.5 flex-1 bg-slate-900 rounded-full overflow-hidden border border-slate-800">
                        <div
                          className={`h-full ${
                            isHighAnomaly ? "bg-amber-400" : "bg-emerald-400"
                          }`}
                          style={{
                            width: `${Math.min(100, (stage.anomaly_score / 4.0) * 100)}%`,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Snapshot Readings */}
                <div>
                  <div className="text-[10px] font-mono text-slate-500 uppercase tracking-wider mb-2">
                    Process Sensor Readings At Moment of Completion
                  </div>
                  {stage.readings && Object.keys(stage.readings).length > 0 ? (
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {Object.entries(stage.readings).map(([key, val]) => {
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
                              {unit && <span className="text-slate-500 ml-0.5">{unit}</span>}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500 italic font-mono">
                      No snapshot sensor data recorded.
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {/* Final QC Station Step in Timeline */}
          <div
            className={`relative scada-panel rounded-xl p-5 border transition-all ${
              isPassed
                ? "border-emerald-500/50 bg-emerald-950/15"
                : isFailed
                ? "border-rose-500/70 bg-rose-950/25"
                : "border-slate-800"
            }`}
          >
            {/* Timeline Dot */}
            <div
              className={`absolute -left-[31px] md:-left-[39px] top-5 w-6 h-6 rounded-full border-2 flex items-center justify-center text-[10px] font-mono font-bold ${
                isPassed
                  ? "bg-emerald-950 border-emerald-400 text-emerald-300"
                  : isFailed
                  ? "bg-rose-950 border-rose-500 text-rose-300"
                  : "bg-slate-950 border-slate-600 text-slate-400"
              }`}
            >
              4
            </div>

            <div className="flex items-center justify-between pb-3 border-b border-slate-800/80">
              <div className="flex items-center gap-2.5">
                <span className="text-lg p-1.5 rounded bg-slate-900 border border-slate-800">
                  🔬
                </span>
                <div>
                  <h3 className="text-sm font-bold font-mono text-slate-100 uppercase">
                    Stage 4: Quality Control & Automated Inspection
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Defect classifier model and multi-stage verification
                  </p>
                </div>
              </div>

              {qc && (
                <span
                  className={`text-xs font-mono font-bold px-2.5 py-1 rounded uppercase border ${
                    isPassed
                      ? "bg-emerald-950 text-emerald-300 border-emerald-500/50"
                      : "bg-rose-950 text-rose-300 border-rose-500/60"
                  }`}
                >
                  {qc.outcome.toUpperCase()}
                </span>
              )}
            </div>

            {/* QC Verdict Content */}
            {qc ? (
              <div className="mt-4 flex flex-col gap-4">
                {isPassed && (
                  <div className="p-4 rounded-lg bg-emerald-950/40 border border-emerald-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                      <div className="text-emerald-400 font-mono font-bold text-base flex items-center gap-2">
                        <span>✓</span>
                        <span>QUALITY INSPECTION PASSED</span>
                      </div>
                      <p className="text-xs text-slate-300 mt-1">
                        All pressure, dimensional, and visual membrane characteristics meet standard specifications.
                      </p>
                    </div>

                    <div className="font-mono text-xs text-slate-400 text-right shrink-0">
                      <div>Defect Probability: {(qc.probability * 100).toFixed(1)}%</div>
                      <div className="text-[10px] text-slate-500">
                        {qc.tested_at ? new Date(qc.tested_at).toLocaleTimeString() : ""}
                      </div>
                    </div>
                  </div>
                )}

                {isFailed && (
                  <div className="p-4 rounded-lg bg-rose-950/50 border border-rose-500/60 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <div className="text-rose-400 font-mono font-bold text-base flex items-center gap-2">
                        <span>✗</span>
                        <span>UNIT FAILED QUALITY VERIFICATION</span>
                      </div>
                      <div className="font-mono text-xs text-rose-300">
                        P(defect) = {(qc.probability * 100).toFixed(1)}%
                      </div>
                    </div>

                    {/* Operator Diagnostic Statement (as explicitly requested) */}
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
            ) : (
              <div className="py-4 text-center text-xs font-mono text-amber-400 bg-amber-950/20 border border-dashed border-amber-500/30 rounded mt-3">
                ⏳ Unit currently in transit across production line; pending final QC inspection.
              </div>
            )}
          </div>
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
