"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { fetchRecentUnits, getErrorMessage, ApiError } from "../../lib/api";
import { safeSessionStorageGet } from "../../lib/plant-utils";
import { TokenEntryCard } from "../../components/telemetry/TokenEntryCard";
import type { RecentUnitItem } from "../../types/factory";
import { useFactoryWebSocket } from "../../context/WebSocketContext";

const STAGE_LABELS: Record<string, { label: string; icon: React.ReactNode }> = {
  housing: {
    label: "1. Housing Sub-Facility",
    icon: (
      <svg className="w-3.5 h-3.5 text-slate-700 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
  },
  casting: {
    label: "2. Membrane Casting",
    icon: (
      <svg className="w-3.5 h-3.5 text-slate-700 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h18M3 16h18" />
      </svg>
    ),
  },
  assembly: {
    label: "3. Assembly Station",
    icon: (
      <svg className="w-3.5 h-3.5 text-slate-700 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
  qc: {
    label: "4. Quality Control",
    icon: (
      <svg className="w-3.5 h-3.5 text-slate-700 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    ),
  },
};

export default function UnitsIndexPage() {
  const router = useRouter();
  const { isSignedIn, getToken } = useAuth();
  const {
    machines,
    selectedPlantId,
    plantsList,
    plantDefinition,
    status,
    isTokenRequired,
    tokenError,
    submitViewerToken,
  } = useFactoryWebSocket();

  const [searchTerm, setSearchTerm] = useState("");
  const [recentUnits, setRecentUnits] = useState<RecentUnitItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);

  const refreshRecent = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setAuthRequired(false);
      let token = safeSessionStorageGet<string | null>(
        `plantpulse_viewer_token_${selectedPlantId}`,
        null
      );
      if (!token && isSignedIn) {
        try {
          token = await getToken();
        } catch (e) {
          console.warn("Failed to get Clerk token for units:", e);
        }
      }
      const data = await fetchRecentUnits(selectedPlantId, 30, token);
      setRecentUnits(data);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        setAuthRequired(true);
        setError("Viewer token required to access units for this plant.");
      } else {
        setError(getErrorMessage(err, "Failed to load recent units"));
      }
    } finally {
      setLoading(false);
    }
  }, [selectedPlantId, isSignedIn, getToken]);

  useEffect(() => {
    let isMounted = true;
    (async () => {
      let token = safeSessionStorageGet<string | null>(
        `plantpulse_viewer_token_${selectedPlantId}`,
        null
      );
      if (!token && isSignedIn) {
        try {
          token = await getToken();
        } catch (e) {
          console.warn("Failed to get Clerk token for units:", e);
        }
      }
      try {
        const data = await fetchRecentUnits(selectedPlantId, 30, token);
        if (!isMounted) return;
        setRecentUnits(data);
      } catch (err: unknown) {
        if (!isMounted) return;
        if (err instanceof ApiError && err.status === 401) {
          setAuthRequired(true);
          setError("Viewer token required to access units for this plant.");
        } else {
          setError(getErrorMessage(err, "Failed to load recent units"));
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    })();
    return () => {
      isMounted = false;
    };
  }, [selectedPlantId, isSignedIn, getToken]);

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
        list.push({
          unitId: m.current_unit_id,
          machineId: m.machine_id,
          machineName: m.name || m.machine_id,
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
    <div className="max-w-5xl mx-auto flex flex-col gap-7 py-2">
      {/* Search Header Hero (Snow & Evocon Clean Style) */}
      <div className="bg-white rounded-3xl p-7 md:p-9 flex flex-col gap-5 border border-slate-300 shadow-sm relative overflow-hidden">
        <div className="flex items-center gap-4 relative z-10">
          <div className="w-12 h-12 rounded-2xl bg-blue-50 border-2 border-blue-200 text-blue-700 flex items-center justify-center shadow-xs">
            <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl md:text-2xl font-bold tracking-tight text-slate-900">
              Unit Traceability & Quality Genealogy
            </h1>
            <p className="text-xs md:text-sm text-slate-600 font-medium mt-1 max-w-2xl">
              Query complete end-to-end manufacturing journey, sensor snapshots, anomaly scores, and root-cause QC defect attribution.
            </p>
          </div>
        </div>

        {/* Search Input Box */}
        <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-3 mt-2 relative z-10">
          <div className="relative flex-1">
            <label htmlFor="main-unit-search" className="sr-only">
              Enter Unit Serial Number
            </label>
            <input
              id="main-unit-search"
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Enter Unit Serial Number (e.g. unit_1011164456_000001)..."
              className="w-full px-5 py-3.5 bg-white rounded-2xl border-2 border-slate-300 font-mono text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-100 text-sm transition-all shadow-xs"
            />
          </div>
          <button
            type="submit"
            className="px-7 py-3.5 rounded-2xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm transition-all flex items-center justify-center gap-2 cursor-pointer shadow-sm hover:scale-[1.01]"
          >
            <span>Trace Unit</span>
            <span>➔</span>
          </button>
        </form>
      </div>

      {/* Viewer Authentication Form */}
      {(isTokenRequired || status === "token_required" || authRequired) && (
        <TokenEntryCard
          plantName={
            plantsList.find((p) => p.plant_id === selectedPlantId)?.name ||
            plantDefinition?.name ||
            selectedPlantId
          }
          plantId={selectedPlantId}
          onSubmit={(token) => {
            submitViewerToken(token);
            setAuthRequired(false);
          }}
          error={tokenError}
        />
      )}

      {/* Section 1: Active In-Flight Units on Factory Floor */}
      <div className="bg-white rounded-3xl p-6 md:p-7 border border-slate-300 flex flex-col gap-4 shadow-sm">
        <div className="flex items-center justify-between pb-3 border-b border-slate-200">
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-500 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-600" />
            </span>
            <h2 className="text-base font-bold text-slate-900 tracking-tight">
              Active In-Flight Units (Live Stations)
            </h2>
          </div>
          <span className="text-xs font-semibold text-slate-700 px-3 py-1 rounded-full bg-slate-100 border border-slate-300">
            {activeInFlightUnits.length} in production right now
          </span>
        </div>

        {activeInFlightUnits.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {activeInFlightUnits.map((u) => {
              const stageInfo = STAGE_LABELS[u.subFacility] || {
                label: u.subFacility,
                icon: (
                  <svg className="w-3.5 h-3.5 text-slate-700 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                  </svg>
                ),
              };
              return (
                <Link
                  key={u.unitId}
                  href={`/units/${encodeURIComponent(u.unitId)}`}
                  className="bg-white rounded-2xl p-4.5 flex flex-col justify-between group transition-all duration-200 border-2 border-slate-200 hover:border-blue-500 hover:-translate-y-0.5 hover:shadow-md"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-mono text-sm font-bold text-blue-600 group-hover:text-blue-800 truncate">
                      {u.unitId}
                    </span>
                    <span className="text-[10px] font-semibold px-2.5 py-0.5 rounded-full border border-blue-300 bg-blue-50 text-blue-700 animate-pulse whitespace-nowrap">
                      In-Flight
                    </span>
                  </div>

                  <div className="mt-3 flex flex-col gap-1.5 text-xs">
                    <div className="flex items-center gap-2 text-slate-900 font-semibold">
                      <span>{stageInfo.icon}</span>
                      <span>{stageInfo.label}</span>
                    </div>
                    <div className="flex items-center justify-between text-slate-600 text-xs font-medium">
                      <span className="truncate">{u.machineName}</span>
                      <span className="text-blue-600 font-bold font-mono">
                        {u.phase ? `[${u.phase}]` : u.machineState}
                      </span>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-slate-600 bg-slate-50 rounded-2xl border border-slate-300 font-medium">
            All stations currently idling or between work cycles. Awaiting next stage cycle.
          </div>
        )}
      </div>

      {/* Section 2: Recent Manufactured Units (Database Registry) */}
      <div className="bg-white rounded-3xl p-6 md:p-7 border border-slate-300 flex flex-col gap-4 shadow-sm">
        <div className="flex items-center justify-between pb-3 border-b border-slate-200">
          <h2 className="text-base font-bold text-slate-900 tracking-tight">
            Recent Manufactured Units Registry
          </h2>
          <button
            onClick={refreshRecent}
            className="text-xs text-slate-700 hover:text-slate-900 px-3 py-1.5 rounded-xl bg-white border border-slate-300 hover:border-slate-400 transition-all flex items-center gap-1.5 cursor-pointer font-semibold shadow-xs"
          >
            <span>↻</span>
            <span>Refresh</span>
          </button>
        </div>

        {error && (
          <div className="p-3.5 rounded-2xl bg-amber-50 border border-amber-300 text-amber-950 text-xs font-semibold">
            {error}
          </div>
        )}

        {loading && recentUnits.length === 0 ? (
          <div className="flex items-center justify-center py-12 gap-2 text-xs text-slate-600 font-medium">
            <div className="w-5 h-5 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
            <span>Loading registered units from database...</span>
          </div>
        ) : recentUnits.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3.5">
            {recentUnits.map((u, idx) => {
              const isPassed = u.status === "passed";
              const isFailed = u.status === "failed";
              const isInProgress = u.status === "in_progress";

              return (
                <Link
                  key={`${u.unit_id}-${idx}`}
                  href={`/units/${encodeURIComponent(u.unit_id)}`}
                  className="bg-white rounded-2xl p-4.5 flex flex-col justify-between group transition-all duration-200 border-2 border-slate-200 hover:border-slate-400 hover:-translate-y-0.5 shadow-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-bold text-slate-900 group-hover:text-blue-600 truncate">
                      {u.unit_id}
                    </span>
                    <span
                      className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border whitespace-nowrap capitalize ${
                        isPassed
                          ? "bg-emerald-50 text-emerald-800 border-emerald-300"
                          : isFailed
                          ? "bg-rose-50 text-rose-800 border-rose-300"
                          : isInProgress
                          ? "bg-blue-50 text-blue-800 border-blue-300"
                          : "bg-slate-100 text-slate-700 border-slate-300"
                      }`}
                    >
                      {u.status}
                    </span>
                  </div>

                  <div className="mt-3 flex items-center justify-between text-xs text-slate-600 font-medium">
                    <span>
                      {u.created_at
                        ? new Date(u.created_at).toLocaleTimeString()
                        : "Registered"}
                    </span>
                    <span className="text-blue-600 group-hover:text-blue-800 font-bold">
                      View Journey →
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-slate-600 bg-slate-50 rounded-2xl border border-slate-300 font-medium">
            No completed units recorded in database yet. Units are recorded as they progress through production.
          </div>
        )}
      </div>
    </div>
  );
}
