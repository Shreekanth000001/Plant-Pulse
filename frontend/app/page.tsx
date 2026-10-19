"use client";

import React, { useState, useMemo } from "react";
import { useFactoryWebSocket } from "../context/WebSocketContext";
import { MachineCard } from "../components/telemetry/MachineCard";
import { QueueHandoffIndicator } from "../components/telemetry/QueueHandoffIndicator";
import { OEEHeader } from "../components/telemetry/OEEHeader";
import { ProductionFlowTopology } from "../components/telemetry/ProductionFlowTopology";
import { StationInspectorModal } from "../components/telemetry/StationInspectorModal";
import { LiveEventTicker } from "../components/telemetry/LiveEventTicker";
import { TokenEntryCard } from "../components/telemetry/TokenEntryCard";
import {
  shouldShowLineIsFillingBanner,
  isModuleEnabled,
} from "../lib/plant-utils";
import type { MachineStatus, MachineDefinition } from "../types/factory";

export default function LiveOverviewPage() {
  const {
    machines,
    handoffs,
    status,
    lastMessageAt,
    plantDefinition,
    recentQcResults,
    isTokenRequired,
    tokenError,
    submitViewerToken,
    selectedPlantId,
    plantsList,
  } = useFactoryWebSocket();

  // Selected machine for inspector modal
  const [selectedMachineId, setSelectedMachineId] = useState<string | null>(null);

  // Filter state for station matrix
  const [statusFilter, setStatusFilter] = useState<"ALL" | "RUNNING" | "STARVED" | "FAULT">("ALL");

  const hasTraceability = isModuleEnabled(
    plantDefinition?.enabled_modules,
    "product_traceability"
  );

  // Dynamic areas from plant definition sorted by display_order
  const sortedAreas = useMemo(() => {
    if (!plantDefinition?.areas) return [];
    return [...plantDefinition.areas].sort(
      (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)
    );
  }, [plantDefinition]);

  // Total machines across all areas
  const allMachineIds = useMemo(() => {
    const ids: string[] = [];
    for (const area of sortedAreas) {
      for (const m of area.machines || []) {
        ids.push(m.machine_code);
      }
    }
    return ids;
  }, [sortedAreas]);

  // Starvation per area for handoff indicators
  const isDownstreamStarved = (areaIndex: number) => {
    if (areaIndex >= sortedAreas.length - 1) return false;
    const nextArea = sortedAreas[areaIndex + 1];
    return (nextArea.machines || []).some(
      (m) => machines[m.machine_code]?.starved
    );
  };

  const activeInFlightCount = useMemo(() => {
    return Object.values(machines).filter((m) => Boolean(m.current_unit_id)).length;
  }, [machines]);

  const machineCounts = useMemo(() => {
    const list = Object.values(machines);
    let running = 0;
    let starved = 0;
    let fault = 0;

    for (const m of list) {
      const state = m.machine_state?.toUpperCase();
      if (state === "FAULT") fault++;
      else if (m.starved) starved++;
      else if (state === "RUNNING" || state === "TESTING") running++;
    }

    return { total: list.length || allMachineIds.length || 0, running, starved, fault };
  }, [machines, allMachineIds]);

  const showFillingBanner = shouldShowLineIsFillingBanner({
    enabledModules: plantDefinition?.enabled_modules,
    qcResultCount: recentQcResults.length,
  });

  let selectedMachine: MachineStatus | null = null;
  let selectedMachineDef: MachineDefinition | undefined = undefined;

  if (selectedMachineId) {
    selectedMachine = machines[selectedMachineId] || null;
    if (plantDefinition?.areas) {
      for (const area of plantDefinition.areas) {
        const found = area.machines?.find((d) => d.machine_code === selectedMachineId);
        if (found) {
          selectedMachineDef = found;
          if (!selectedMachine) {
            selectedMachine = {
              machine_id: found.machine_code,
              name: found.name,
              area_code: area.area_code,
              sub_facility: area.area_code,
              machine_state: "OFFLINE",
              starved: false,
              extra: {},
            };
          }
          break;
        }
      }
    }
  }

  return (
    <div className="flex flex-col gap-8 pb-10">
      {/* Station Inspector Modal */}
      {selectedMachineId && (
        <StationInspectorModal
          machineId={selectedMachineId}
          machine={selectedMachine}
          machineDef={selectedMachineDef}
          onClose={() => setSelectedMachineId(null)}
        />
      )}

      {/* Top SCADA Pacing & Live Synchrony Sub-bar */}
      <div className="bg-white rounded-2xl px-5 py-3 border border-slate-200/90 flex flex-col md:flex-row md:items-center justify-between text-xs text-slate-600 gap-3 shadow-xs">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                status === "connected"
                  ? "bg-emerald-500 animate-pulse"
                  : status === "token_required"
                  ? "bg-blue-500 animate-pulse"
                  : status === "reconnecting"
                  ? "bg-amber-500 animate-ping"
                  : "bg-rose-500"
              }`}
            />
            <span className="text-slate-900 font-semibold">
              Operational Telemetry:{" "}
              <span className="capitalize">
                {status === "token_required" ? "Token Plant (Snapshot Mode)" : status}
              </span>
            </span>
          </span>
          <span className="text-slate-300">|</span>
          <span>
            Tick:{" "}
            <span className="text-blue-600 font-mono tabular-nums font-bold">
              {lastMessageAt ? new Date(lastMessageAt).toLocaleTimeString() : "Awaiting telemetry"}
            </span>
          </span>
        </div>

        {hasTraceability && (
          <div className="flex items-center gap-4 text-slate-500">
            <span>
              Floor WIP:{" "}
              <strong className="text-blue-700 font-mono tabular-nums font-bold">
                {activeInFlightCount} in-flight
              </strong>
            </span>
            <span className="text-slate-300">|</span>
            <span>
              Inter-Stage Buffers:{" "}
              <strong className="text-amber-800 font-mono tabular-nums font-bold">
                {handoffs.housingToCasting + handoffs.castingToAssembly + handoffs.assemblyToQc} units
              </strong>
            </span>
          </div>
        )}
      </div>

      {/* Viewer Authentication Form */}
      {(isTokenRequired || status === "token_required") && (
        <TokenEntryCard
          plantName={
            plantsList.find((p) => p.plant_id === selectedPlantId)?.name ||
            plantDefinition?.name ||
            selectedPlantId
          }
          plantId={selectedPlantId}
          onSubmit={submitViewerToken}
          error={tokenError}
        />
      )}

      {/* Disconnected Alert Banner (if offline and no machines loaded) */}
      {status === "disconnected" && Object.keys(machines).length === 0 && (
        <div
          role="alert"
          className="p-4.5 rounded-2xl bg-rose-50 border-2 border-rose-300 text-rose-950 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs"
        >
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-rose-100 border border-rose-300 flex items-center justify-center text-rose-700 font-bold shrink-0 text-base">
              !
            </div>
            <div>
              <h3 className="text-xs font-bold text-rose-900">
                Telemetry Stream Disconnected
              </h3>
              <p className="text-xs text-rose-800 mt-0.5">
                Unable to establish connection to factory telemetry server. Verify the backend FastAPI service is running on port 8000.
              </p>
            </div>
          </div>
          <span className="text-xs font-mono font-semibold px-2.5 py-1 rounded-lg bg-white border border-rose-200 text-rose-700 whitespace-nowrap">
            Status: OFFLINE
          </span>
        </div>
      )}

      {/* Line is Filling Banner (Data-driven only: quality_inspection enabled and 0 QC results) */}
      {showFillingBanner && (
        <div
          role="status"
          className="p-4 rounded-2xl bg-blue-50 border-2 border-blue-300 text-blue-950 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs"
        >
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-blue-100 border border-blue-300 flex items-center justify-center text-blue-700 font-bold shrink-0 text-base">
              ℹ
            </div>
            <div>
              <h4 className="text-xs font-bold text-blue-900">
                Line is filling
              </h4>
              <p className="text-xs text-blue-800 mt-0.5">
                First production cycle in progress — awaiting initial end-of-line quality verification results.
              </p>
            </div>
          </div>
          <span className="text-xs font-mono font-semibold px-2.5 py-1 rounded-lg bg-white border border-blue-200 text-blue-700 whitespace-nowrap">
            QC Pending
          </span>
        </div>
      )}

      {/* 1. Executive OEE Overview & Shift Rhythm */}
      <OEEHeader machines={machines} />

      {/* 2. Interactive Plant Facility Topology */}
      <ProductionFlowTopology
        definition={plantDefinition}
        machines={machines}
        handoffs={handoffs}
        onSelectMachine={(id) => setSelectedMachineId(id)}
      />

      {/* 3. Station Matrix Filter & Production Areas */}
      <div className="flex flex-col gap-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900 tracking-tight">
              Facility Areas & Assets
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Live individual station telemetry, process reading gauges, and maintenance vibration sensors.
            </p>
          </div>

          {/* Status Filter Buttons with Accessible ARIA Group */}
          <div
            role="group"
            aria-label="Filter stations by operating status"
            className="flex items-center p-1 rounded-xl bg-slate-100 border border-slate-200 text-xs shadow-inner"
          >
            <button
              onClick={() => setStatusFilter("ALL")}
              aria-pressed={statusFilter === "ALL"}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                statusFilter === "ALL"
                  ? "bg-white text-slate-900 shadow-xs border border-slate-200 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white/50"
              }`}
            >
              All ({machineCounts.total})
            </button>
            <button
              onClick={() => setStatusFilter("RUNNING")}
              aria-pressed={statusFilter === "RUNNING"}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                statusFilter === "RUNNING"
                  ? "bg-white text-emerald-700 shadow-xs border border-slate-200 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white/50"
              }`}
            >
              Running ({machineCounts.running})
            </button>
            <button
              onClick={() => setStatusFilter("STARVED")}
              aria-pressed={statusFilter === "STARVED"}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                statusFilter === "STARVED"
                  ? "bg-white text-amber-800 shadow-xs border border-slate-200 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white/50"
              }`}
            >
              Starved ({machineCounts.starved})
            </button>
            <button
              onClick={() => setStatusFilter("FAULT")}
              aria-pressed={statusFilter === "FAULT"}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                statusFilter === "FAULT"
                  ? "bg-white text-rose-700 shadow-xs border border-slate-200 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-white/50"
              }`}
            >
              Faults ({machineCounts.fault})
            </button>
          </div>
        </div>

        {/* Dynamic Areas List */}
        <div className="flex flex-col gap-6">
          {sortedAreas.map((area, idx) => {
            const areaMachinesDef = [...(area.machines || [])].sort(
              (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)
            );

            const rawAreaMachines = areaMachinesDef.map((mDef) => {
              return (
                machines[mDef.machine_code] || {
                  machine_id: mDef.machine_code,
                  name: mDef.name,
                  area_code: area.area_code,
                  sub_facility: area.area_code,
                  machine_state: "OFFLINE",
                  starved: false,
                  extra: {},
                }
              );
            });

            // Filter machines based on selected status filter
            const filteredMachines = rawAreaMachines.filter((m) => {
              if (statusFilter === "ALL") return true;
              const state = m.machine_state?.toUpperCase();
              if (statusFilter === "RUNNING")
                return (state === "RUNNING" || state === "TESTING") && !m.starved;
              if (statusFilter === "STARVED") return m.starved;
              if (statusFilter === "FAULT") return state === "FAULT";
              return true;
            });

            const activeCount = rawAreaMachines.filter(
              (m) => m.machine_state === "RUNNING" || m.machine_state === "TESTING"
            ).length;
            const areaHasStarved = rawAreaMachines.some((m) => m.starved);

            return (
              <React.Fragment key={area.area_code}>
                {/* Area Section Container */}
                <section className="bg-white rounded-3xl p-6 lg:p-7 flex flex-col gap-5 border border-slate-200/90 shadow-xs">
                  {/* Area Header */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 gap-3">
                    <div className="flex items-center gap-3.5">
                      <div className="w-11 h-11 rounded-2xl bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-700 font-bold font-mono text-sm shadow-xs">
                        {idx + 1}
                      </div>
                      <div>
                        <h3 className="text-base font-bold text-slate-900 tracking-tight">
                          {area.name}
                        </h3>
                        <p className="text-xs text-slate-500 font-mono mt-0.5">
                          Area Code: {area.area_code}
                        </p>
                      </div>
                    </div>

                    {/* Area Metrics Badges */}
                    <div className="flex items-center gap-2 text-xs">
                      <span className="px-3 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200 font-medium font-mono tabular-nums">
                        {rawAreaMachines.length}{" "}
                        {rawAreaMachines.length === 1 ? "Station" : "Stations"}
                      </span>
                      <span className="px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold flex items-center gap-1.5 font-mono tabular-nums">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        {activeCount} Active
                      </span>
                      {areaHasStarved && (
                        <span className="px-3 py-1 rounded-full bg-amber-50 text-amber-800 border border-amber-200 font-semibold flex items-center gap-1.5 animate-pulse">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                          Starved
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Grid of Machine Status Cards */}
                  {filteredMachines.length > 0 ? (
                    <div
                      className={`grid grid-cols-1 md:grid-cols-2 ${
                        areaMachinesDef.length >= 4
                          ? "xl:grid-cols-4"
                          : areaMachinesDef.length === 3
                          ? "xl:grid-cols-3"
                          : "xl:grid-cols-2"
                      } gap-4`}
                    >
                      {filteredMachines.map((m) => (
                        <MachineCard
                          key={m.machine_id}
                          machine={m}
                          machineDef={areaMachinesDef.find((d) => d.machine_code === m.machine_id)}
                          onInspect={() => setSelectedMachineId(m.machine_id)}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="p-6 text-center text-xs text-slate-500 italic bg-slate-50 rounded-2xl border border-slate-200">
                      No stations match the selected &quot;{statusFilter}&quot; filter in this area.
                    </div>
                  )}
                </section>

                {/* Inter-Stage Queue Depth Indicators (only rendered when product_traceability enabled) */}
                {hasTraceability && idx === 0 && sortedAreas.length > 1 && (
                  <QueueHandoffIndicator
                    fromStage={sortedAreas[0]?.name || "Stage 1"}
                    toStage={sortedAreas[1]?.name || "Stage 2"}
                    depth={handoffs.housingToCasting}
                    isDownstreamStarved={isDownstreamStarved(0)}
                  />
                )}

                {hasTraceability && idx === 1 && sortedAreas.length > 2 && (
                  <QueueHandoffIndicator
                    fromStage={sortedAreas[1]?.name || "Stage 2"}
                    toStage={sortedAreas[2]?.name || "Stage 3"}
                    depth={handoffs.castingToAssembly}
                    isDownstreamStarved={isDownstreamStarved(1)}
                  />
                )}

                {hasTraceability && idx === 2 && sortedAreas.length > 3 && (
                  <QueueHandoffIndicator
                    fromStage={sortedAreas[2]?.name || "Stage 3"}
                    toStage={sortedAreas[3]?.name || "Stage 4"}
                    depth={handoffs.assemblyToQc}
                    isDownstreamStarved={isDownstreamStarved(2)}
                  />
                )}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {/* 4. Real-Time Factory Floor Event Stream (Audit Log) */}
      <LiveEventTicker />
    </div>
  );
}
