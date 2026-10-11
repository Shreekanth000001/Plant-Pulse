"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { fetchRecentUnits, getErrorMessage } from "../../lib/api";
import { RecentUnitItem, KNOWN_MACHINES } from "../../types/factory";
import { useFactoryWebSocket } from "../../context/WebSocketContext";

const STAGE_LABELS: Record<string, { label: string; icon: string }> = {
  housing: { label: "1. Housing (Molding)", icon: "🏗️" },
  casting: { label: "2. Membrane Casting", icon: "🎞️" },
  assembly: { label: "3. Assembly", icon: "⚙️" },
  qc: { label: "4. QC Testing", icon: "🔬" },
};

export default function UnitsIndexPage() {
  const router = useRouter();
  const { machines } = useFactoryWebSocket();

  const [searchTerm, setSearchTerm] = useState("");
  const [recentUnits, setRecentUnits] = useState<RecentUnitItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshRecent = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchRecentUnits(30);
      setRecentUnits(data);
    } catch (err: unknown) {
      setError(getErrorMessage(err, "Failed to load recent units"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    fetchRecentUnits(30)
      .then((data) => {
        if (!isMounted) return;
        setRecentUnits(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        setError(getErrorMessage(err, "Failed to load recent units"));
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  // Extract currently active units from live machines telemetry
  const activeInFlightUnits = useMemo(() => {
    const list: {
      unitId: string;
      machineId: string;
      machineName: string;
      subFacility: string;
      phase?: string | null;
      machineState: string;
      starved: boolean;
    }[] = [];

    const seenUnits = new Set<string>();

    for (const m of Object.values(machines)) {
      if (m.current_unit_id && !seenUnits.has(m.current_unit_id)) {
        seenUnits.add(m.current_unit_id);
        const meta = KNOWN_MACHINES[m.machine_id];
        list.push({
          unitId: m.current_unit_id,
          machineId: m.machine_id,
          machineName: meta?.name || m.name || m.machine_id,
          subFacility: m.sub_facility,
          phase: m.phase,
          machineState: m.machine_state || "IDLE",
          starved: m.starved,
        });
      }
    }

    return list;
  }, [machines]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchTerm.trim()) return;
    router.push(`/units/${encodeURIComponent(searchTerm.trim())}`);
  };

  return (
    <div className="max-w-5xl mx-auto flex flex-col gap-6 py-4">
      {/* Search Header Hero */}
      <div className="scada-panel rounded-xl p-6 md:p-8 flex flex-col gap-4 border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-3 rounded-lg bg-cyan-950/60 border border-cyan-500/40 text-cyan-400 text-2xl font-mono">
            🔍
          </div>
          <div>
            <h1 className="text-xl md:text-2xl font-bold font-mono text-slate-100 uppercase tracking-wide">
              Unit Traceability & Quality Lookup
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Query complete end-to-end manufacturing genealogies, process sensor snapshots, anomaly scores, and root-cause QC defect attribution.
            </p>
          </div>
        </div>

        {/* Search Input Box */}
        <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-2 mt-4">
          <div className="relative flex-1">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Enter Unit Serial Number (e.g. unit_1011164456_000001)..."
              className="w-full px-4 py-3 bg-slate-950 rounded-lg border border-slate-700 font-mono text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 text-sm"
              autoFocus
            />
          </div>
          <button
            type="submit"
            className="px-6 py-3 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-mono font-bold text-sm transition-colors flex items-center justify-center gap-2 cursor-pointer shadow-[0_0_15px_rgba(6,182,212,0.3)]"
          >
            <span>TRACE UNIT</span>
            <span>➔</span>
          </button>
        </form>
      </div>

      {/* Section 1: Active In-Flight Units on Factory Floor */}
      <div className="scada-panel rounded-xl p-6 border-slate-800 flex flex-col gap-4">
        <div className="flex items-center justify-between pb-2 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse" />
            <h2 className="text-sm font-bold font-mono text-cyan-300 uppercase tracking-wider">
              Active In-Flight Units (Live Stations)
            </h2>
          </div>
          <span className="text-xs font-mono text-slate-400">
            {activeInFlightUnits.length} in production right now
          </span>
        </div>

        {activeInFlightUnits.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {activeInFlightUnits.map((u) => {
              const stageInfo = STAGE_LABELS[u.subFacility] || {
                label: u.subFacility,
                icon: "📦",
              };
              return (
                <Link
                  key={u.unitId}
                  href={`/units/${encodeURIComponent(u.unitId)}`}
                  className="bg-slate-950/80 border border-cyan-500/30 hover:border-cyan-400 rounded-lg p-3.5 flex flex-col justify-between group transition-all shadow-[0_0_12px_rgba(6,182,212,0.1)]"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-mono text-sm font-bold text-cyan-300 group-hover:text-cyan-200 truncate">
                      {u.unitId}
                    </span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded uppercase border bg-cyan-950/60 text-cyan-300 border-cyan-500/40 animate-pulse whitespace-nowrap">
                      IN-FLIGHT
                    </span>
                  </div>

                  <div className="mt-2.5 flex flex-col gap-1 text-xs font-mono">
                    <div className="flex items-center gap-1.5 text-slate-200">
                      <span>{stageInfo.icon}</span>
                      <span className="font-semibold">{stageInfo.label}</span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-slate-400">
                      <span className="truncate">{u.machineName}</span>
                      <span className="text-cyan-400 font-medium">
                        {u.phase ? `[${u.phase}]` : u.machineState}
                      </span>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="p-6 text-center text-xs font-mono text-slate-500 bg-slate-950/40 rounded-lg border border-slate-800/60">
            All stations currently idling or between work cycles. Awaiting next stage cycle.
          </div>
        )}
      </div>

      {/* Section 2: Recent Manufactured Units (Database Registry) */}
      <div className="scada-panel rounded-xl p-6 border-slate-800 flex flex-col gap-4">
        <div className="flex items-center justify-between pb-2 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold font-mono text-slate-300 uppercase tracking-wider">
              Recent Manufactured Units Registry
            </h2>
          </div>
          <button
            onClick={refreshRecent}
            className="text-xs font-mono text-slate-400 hover:text-cyan-300 px-2.5 py-1 rounded bg-slate-900 border border-slate-800 hover:border-slate-700 transition-colors flex items-center gap-1 cursor-pointer"
          >
            <span>↻</span>
            <span>Refresh</span>
          </button>
        </div>

        {error && (
          <div className="p-3 rounded bg-amber-950/50 border border-amber-600/40 text-amber-300 font-mono text-xs">
            {error}
          </div>
        )}

        {loading && recentUnits.length === 0 ? (
          <div className="flex items-center justify-center py-10 gap-2 font-mono text-xs text-slate-400">
            <div className="w-5 h-5 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin" />
            <span>Loading registered units from database...</span>
          </div>
        ) : recentUnits.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {recentUnits.map((u) => {
              const isPassed = u.status === "passed";
              const isFailed = u.status === "failed";
              const isInProgress = u.status === "in_progress";

              return (
                <Link
                  key={u.unit_id}
                  href={`/units/${encodeURIComponent(u.unit_id)}`}
                  className="bg-slate-950/70 border border-slate-800 hover:border-cyan-500/50 rounded-lg p-3.5 flex flex-col justify-between group transition-all"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-semibold text-slate-200 group-hover:text-cyan-300 truncate">
                      {u.unit_id}
                    </span>
                    <span
                      className={`text-[10px] font-mono px-1.5 py-0.5 rounded uppercase border whitespace-nowrap ${
                        isPassed
                          ? "bg-emerald-950/60 text-emerald-400 border-emerald-500/30"
                          : isFailed
                          ? "bg-rose-950/60 text-rose-400 border-rose-500/30"
                          : isInProgress
                          ? "bg-cyan-950/60 text-cyan-300 border-cyan-500/30"
                          : "bg-slate-800 text-slate-400 border-slate-700"
                      }`}
                    >
                      {u.status}
                    </span>
                  </div>

                  <div className="mt-3 flex items-center justify-between text-xs text-slate-400 font-mono">
                    <span className="text-[11px] text-slate-500">
                      {u.created_at
                        ? new Date(u.created_at).toLocaleTimeString()
                        : "Registered"}
                    </span>
                    <span className="text-cyan-400/80 group-hover:text-cyan-300 text-[11px]">
                      View Journey →
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="p-8 text-center text-xs font-mono text-slate-500 bg-slate-950/40 rounded-lg border border-slate-800/60">
            No completed units recorded in database yet. Units are recorded as they progress through production.
          </div>
        )}
      </div>
    </div>
  );
}
