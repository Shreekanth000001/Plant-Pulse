"use client";

import React, { useState, useMemo } from "react";
import { KNOWN_MACHINES } from "../types/factory";
import { useFactoryWebSocket } from "../context/WebSocketContext";
import { MachineCard } from "../components/telemetry/MachineCard";
import { QueueHandoffIndicator } from "../components/telemetry/QueueHandoffIndicator";
import { OEEHeader } from "../components/telemetry/OEEHeader";
import { ProductionFlowTopology } from "../components/telemetry/ProductionFlowTopology";
import { StationInspectorModal } from "../components/telemetry/StationInspectorModal";
import { LiveEventTicker } from "../components/telemetry/LiveEventTicker";

interface StageConfig {
  id: "housing" | "casting" | "assembly" | "qc";
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  expectedMachineIds: string[];
}

const STAGES: StageConfig[] = [
  {
    id: "housing",
    title: "1. Housing Sub-Facility",
    subtitle: "Precision polymer molding of outer filter cartridges",
    icon: (
      <svg className="w-5 h-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
    expectedMachineIds: ["hm_01", "hm_02", "hm_03", "hm_04"],
  },
  {
    id: "casting",
    title: "2. Membrane Casting",
    subtitle: "Polymer dope extrusion, phase inversion & film formation",
    icon: (
      <svg className="w-5 h-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h18M3 16h18" />
      </svg>
    ),
    expectedMachineIds: ["cs_01", "cs_02", "cs_03"],
  },
  {
    id: "assembly",
    title: "3. Assembly Station",
    subtitle: "Membrane insertion, robotic torque fitting & ultrasonic sealing",
    icon: (
      <svg className="w-5 h-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    expectedMachineIds: ["am_01", "am_02", "am_03"],
  },
  {
    id: "qc",
    title: "4. Quality Control & Testing",
    subtitle: "Automated integrity inspection, leak testing & defect attribution",
    icon: (
      <svg className="w-5 h-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    ),
    expectedMachineIds: ["qc_01"],
  },
];

export default function LiveOverviewPage() {
  const { machines, handoffs, status, lastMessageAt } = useFactoryWebSocket();

  // Selected machine for inspector modal
  const [selectedMachineId, setSelectedMachineId] = useState<string | null>(null);

  // Filter state for station matrix
  const [statusFilter, setStatusFilter] = useState<"ALL" | "RUNNING" | "STARVED" | "FAULT">("ALL");

  // Check starvation per stage for handoff indicators
  const isCastingStarved = useMemo(() => {
    return STAGES[1].expectedMachineIds.some((id) => machines[id]?.starved);
  }, [machines]);

  const isAssemblyStarved = useMemo(() => {
    return STAGES[2].expectedMachineIds.some((id) => machines[id]?.starved);
  }, [machines]);

  const isQcStarved = useMemo(() => {
    return STAGES[3].expectedMachineIds.some((id) => machines[id]?.starved);
  }, [machines]);

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

    return { total: list.length || 11, running, starved, fault };
  }, [machines]);

  return (
    <div className="flex flex-col gap-8 pb-10">
      {/* Station Inspector Modal */}
      {selectedMachineId && (
        <StationInspectorModal
          machineId={selectedMachineId}
          machine={machines[selectedMachineId] || null}
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
                  : status === "reconnecting"
                  ? "bg-amber-500 animate-ping"
                  : "bg-rose-500"
              }`}
            />
            <span className="text-slate-900 font-semibold">
              Line Operational Telemetry: <span className="capitalize">{status}</span>
            </span>
          </span>
          <span className="text-slate-300">|</span>
          <span>
            Tick:{" "}
            <span className="text-blue-600 font-mono font-bold">
              {lastMessageAt ? new Date(lastMessageAt).toLocaleTimeString() : "Awaiting tick"}
            </span>
          </span>
        </div>

        <div className="flex items-center gap-4 text-slate-500">
          <span>
            Floor Work-In-Progress:{" "}
            <strong className="text-blue-700 font-mono font-bold">{activeInFlightCount} in-flight</strong>
          </span>
          <span className="text-slate-300">|</span>
          <span>
            Inter-Stage Buffers:{" "}
            <strong className="text-amber-800 font-mono font-bold">
              {handoffs.housingToCasting + handoffs.castingToAssembly + handoffs.assemblyToQc} units
            </strong>
          </span>
        </div>
      </div>

      {/* Disconnected Alert Banner (if offline and no machines loaded) */}
      {status === "disconnected" && Object.keys(machines).length === 0 && (
        <div role="alert" className="p-4.5 rounded-2xl bg-rose-50 border-2 border-rose-300 text-rose-950 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs">
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

      {/* 1. Executive OEE Overview & Shift Rhythm */}
      <OEEHeader machines={machines} />

      {/* 2. Interactive Production Flow Topology (Interactive Process Flow) */}
      <ProductionFlowTopology
        machines={machines}
        handoffs={handoffs}
        onSelectMachine={(id) => setSelectedMachineId(id)}
      />

      {/* 3. Station Matrix Filter & Production Stages */}
      <div className="flex flex-col gap-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900 tracking-tight">
              Production Stage Stations
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

        {/* Stages List */}
        <div className="flex flex-col gap-6">
          {STAGES.map((stage, idx) => {
            const rawStageMachines = stage.expectedMachineIds.map(
              (id) =>
                machines[id] || {
                  machine_id: id,
                  name: KNOWN_MACHINES[id]?.name || id,
                  sub_facility: stage.id,
                  machine_state: "IDLE",
                  starved: false,
                  extra: {},
                }
            );

            // Filter machines based on selected status filter
            const stageMachines = rawStageMachines.filter((m) => {
              if (statusFilter === "ALL") return true;
              const state = m.machine_state?.toUpperCase();
              if (statusFilter === "RUNNING") return (state === "RUNNING" || state === "TESTING") && !m.starved;
              if (statusFilter === "STARVED") return m.starved;
              if (statusFilter === "FAULT") return state === "FAULT";
              return true;
            });

            const activeCount = rawStageMachines.filter(
              (m) => m.machine_state === "RUNNING" || m.machine_state === "TESTING"
            ).length;
            const stageHasStarved = rawStageMachines.some((m) => m.starved);

            return (
              <React.Fragment key={stage.id}>
                {/* Stage Container */}
                <section className="bg-white rounded-3xl p-6 lg:p-7 flex flex-col gap-5 border border-slate-200/90 shadow-xs">
                  {/* Stage Header */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 gap-3">
                    <div className="flex items-center gap-3.5">
                      <div className="w-11 h-11 rounded-2xl bg-slate-50 border border-slate-200 flex items-center justify-center shadow-xs">
                        {stage.icon}
                      </div>
                      <div>
                        <h3 className="text-base font-bold text-slate-900 tracking-tight">
                          {stage.title}
                        </h3>
                        <p className="text-xs text-slate-500 mt-0.5">
                          {stage.subtitle}
                        </p>
                      </div>
                    </div>

                    {/* Stage Metrics Badges */}
                    <div className="flex items-center gap-2 text-xs">
                      <span className="px-3 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200 font-medium">
                        {rawStageMachines.length} {rawStageMachines.length === 1 ? "Station" : "Stations"}
                      </span>
                      <span className="px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        {activeCount} Active
                      </span>
                      {stageHasStarved && (
                        <span className="px-3 py-1 rounded-full bg-amber-50 text-amber-800 border border-amber-200 font-semibold flex items-center gap-1.5 animate-pulse">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                          Starved
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Grid of Machine Status Cards */}
                  {stageMachines.length > 0 ? (
                    <div
                      className={`grid grid-cols-1 md:grid-cols-2 ${
                        stage.expectedMachineIds.length >= 4
                          ? "xl:grid-cols-4"
                          : stage.expectedMachineIds.length === 3
                          ? "xl:grid-cols-3"
                          : "xl:grid-cols-2"
                      } gap-4`}
                    >
                      {stageMachines.map((m) => (
                        <MachineCard
                          key={m.machine_id}
                          machine={m}
                          onInspect={() => setSelectedMachineId(m.machine_id)}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="p-6 text-center text-xs text-slate-500 italic bg-slate-50 rounded-2xl border border-slate-200">
                      No stations match the selected &quot;{statusFilter}&quot; filter in this stage.
                    </div>
                  )}
                </section>

                {/* Inter-Stage Queue Depth Indicators */}
                {idx === 0 && (
                  <QueueHandoffIndicator
                    fromStage="Housing (Molding)"
                    toStage="Membrane Casting (Extrusion)"
                    depth={handoffs.housingToCasting}
                    isDownstreamStarved={isCastingStarved}
                  />
                )}

                {idx === 1 && (
                  <QueueHandoffIndicator
                    fromStage="Membrane Casting"
                    toStage="Assembly Station"
                    depth={handoffs.castingToAssembly}
                    isDownstreamStarved={isAssemblyStarved}
                  />
                )}

                {idx === 2 && (
                  <QueueHandoffIndicator
                    fromStage="Assembly Station"
                    toStage="QC (Testing Station)"
                    depth={handoffs.assemblyToQc}
                    isDownstreamStarved={isQcStarved}
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
