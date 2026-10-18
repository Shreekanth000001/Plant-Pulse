"use client";

import React, { useMemo } from "react";
import type {
  MachineStatus,
  QueueHandoffs,
  PublicPlantDefinition,
} from "../../types/factory";

interface ProductionFlowTopologyProps {
  definition?: PublicPlantDefinition | null;
  machines: Record<string, MachineStatus>;
  handoffs: QueueHandoffs;
  onSelectMachine: (machineId: string) => void;
}

export function ProductionFlowTopology({
  definition,
  machines,
  handoffs,
  onSelectMachine,
}: ProductionFlowTopologyProps) {
  const hasTraceability = Boolean(
    definition?.enabled_modules?.includes("product_traceability")
  );

  const flowStages = useMemo(() => {
    if (!definition?.areas || definition.areas.length === 0) return [];

    return [...definition.areas]
      .sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0))
      .map((area, idx) => ({
        id: area.area_code,
        name: area.name,
        stageNum: idx + 1,
        machineIds: [...(area.machines || [])]
          .sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0))
          .map((m) => m.machine_code),
      }));
  }, [definition]);

  const getQueueInfo = (idx: number) => {
    if (!hasTraceability) return null;
    if (idx === 0 && flowStages.length > 1) {
      return {
        depth: handoffs.housingToCasting,
        from: flowStages[0]?.name || "Stage 1",
        to: flowStages[1]?.name || "Stage 2",
      };
    }
    if (idx === 1 && flowStages.length > 2) {
      return {
        depth: handoffs.castingToAssembly,
        from: flowStages[1]?.name || "Stage 2",
        to: flowStages[2]?.name || "Stage 3",
      };
    }
    if (idx === 2 && flowStages.length > 3) {
      return {
        depth: handoffs.assemblyToQc,
        from: flowStages[2]?.name || "Stage 3",
        to: flowStages[3]?.name || "Stage 4",
      };
    }
    return null;
  };

  if (flowStages.length === 0) {
    return null;
  }

  const gridColsClass =
    flowStages.length === 1
      ? "grid-cols-1"
      : flowStages.length === 2
      ? "grid-cols-1 lg:grid-cols-2"
      : flowStages.length === 3
      ? "grid-cols-1 lg:grid-cols-3"
      : "grid-cols-1 lg:grid-cols-4";

  return (
    <div className="bg-white border border-slate-200/90 rounded-3xl p-6 lg:p-7 shadow-xs flex flex-col gap-6 relative overflow-hidden transition-all">
      {/* Topology Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600 shadow-xs">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
            </svg>
          </div>
          <div>
            <h2 className="text-base lg:text-lg font-bold text-slate-900 tracking-tight flex items-center gap-2">
              <span>Plant Facility Topology</span>
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                {flowStages.length} {flowStages.length === 1 ? "Area" : "Areas"}
              </span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Real-time operational status across plant production stations and equipment.
            </p>
          </div>
        </div>

        <div className="text-xs text-slate-600 flex items-center gap-3">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span>Running</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-400" />
            <span>Starved</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-rose-500" />
            <span>Fault</span>
          </span>
        </div>
      </div>

      {/* Visual Pipeline Stage Nodes & Transfer Buffers Flow */}
      <div className={`grid ${gridColsClass} gap-4 items-stretch relative`}>
        {flowStages.map((stage, idx) => {
          const queue = getQueueInfo(idx);
          const stageMachines = stage.machineIds.map((id) => machines[id]);
          const runningCount = stageMachines.filter(
            (m) => m && (m.machine_state === "RUNNING" || m.machine_state === "TESTING")
          ).length;
          const starvedCount = stageMachines.filter((m) => m && m.starved).length;
          const faultCount = stageMachines.filter((m) => m && m.machine_state === "FAULT").length;

          return (
            <div key={stage.id} className="flex flex-col gap-3 relative">
              {/* Stage Node Container */}
              <div className="bg-slate-50/70 border border-slate-200 hover:border-slate-300 hover:bg-white rounded-2xl p-4.5 flex-1 flex flex-col justify-between transition-all shadow-xs group">
                {/* Stage Header */}
                <div className="flex items-center justify-between pb-3 border-b border-slate-200/80">
                  <div className="flex items-center gap-2.5">
                    <span className="w-7 h-7 rounded-lg bg-blue-100/70 border border-blue-200 flex items-center justify-center text-blue-700 text-xs font-bold font-mono">
                      {stage.stageNum}
                    </span>
                    <div>
                      <div className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                        <span>{stage.name}</span>
                      </div>
                      <div className="text-[10px] text-slate-500 font-mono">
                        {stage.machineIds.length} {stage.machineIds.length === 1 ? "Station" : "Stations"}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Stations Pucks in this stage */}
                <div className="my-3 flex flex-col gap-2">
                  <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                    Assigned Assets ({stage.machineIds.length})
                  </div>
                  <div className="grid grid-cols-1 gap-2">
                    {stage.machineIds.map((machineId) => {
                      const m = machines[machineId];
                      const displayName = m?.name || machineId;
                      const state = m?.machine_state?.toUpperCase() || "IDLE";
                      const isStarved = m?.starved;
                      const hasUnit = Boolean(m?.current_unit_id);

                      let dotBg = "bg-amber-400";
                      let borderStyle = "border-slate-200/80";

                      if (state === "FAULT") {
                        dotBg = "bg-rose-500 animate-ping";
                        borderStyle = "border-rose-300 bg-rose-50/50";
                      } else if (state === "RUNNING" || state === "TESTING") {
                        dotBg = "bg-emerald-500";
                        borderStyle = "border-emerald-200 bg-emerald-50/30";
                      } else if (isStarved) {
                        dotBg = "bg-amber-400";
                        borderStyle = "border-amber-200 bg-amber-50/30";
                      }

                      return (
                        <button
                          key={machineId}
                          onClick={() => onSelectMachine(machineId)}
                          className={`w-full p-2.5 rounded-xl border ${borderStyle} bg-white hover:bg-slate-50 transition-all flex items-center justify-between text-left cursor-pointer group/item hover:border-blue-400 hover:shadow-xs`}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={`w-2 h-2 rounded-full ${dotBg} shrink-0`} />
                            <div className="min-w-0">
                              <div className="text-xs font-semibold text-slate-800 truncate group-hover/item:text-blue-600 transition-colors">
                                {displayName}
                              </div>
                              <div className="text-[10px] font-mono tabular-nums text-slate-500 truncate">
                                {hasTraceability && hasUnit ? (
                                  <span className="text-blue-600 font-medium">Unit: {m.current_unit_id}</span>
                                ) : (
                                  <span className="text-slate-400 capitalize">{state.toLowerCase()}</span>
                                )}
                              </div>
                            </div>
                          </div>

                          <svg className="w-3.5 h-3.5 text-slate-400 group-hover/item:text-blue-600 transition-colors shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                          </svg>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Stage Health Footer */}
                <div className="pt-2.5 border-t border-slate-200/80 flex items-center justify-between text-[11px] text-slate-500">
                  <span>
                    Active: <strong className="text-emerald-700 font-mono tabular-nums font-semibold">{runningCount}</strong>
                  </span>
                  <span>
                    Starved: <strong className={starvedCount > 0 ? "text-amber-700 font-mono tabular-nums font-semibold" : "text-slate-500 font-mono tabular-nums"}>{starvedCount}</strong>
                  </span>
                  <span>
                    Fault: <strong className={faultCount > 0 ? "text-rose-600 font-mono tabular-nums font-bold" : "text-slate-500 font-mono tabular-nums"}>{faultCount}</strong>
                  </span>
                </div>
              </div>

              {/* Mobile Inter-Stage Buffer Pill */}
              {queue && (
                <div className="lg:hidden flex items-center justify-center -my-1 py-1">
                  <div className="px-3 py-1 rounded-full bg-slate-50 border border-slate-300 text-[11px] font-mono tabular-nums text-blue-700 shadow-2xs flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />
                    <span className="font-semibold">{queue.from} ➔ {queue.to}: {queue.depth} in buffer</span>
                  </div>
                </div>
              )}

              {/* Inter-Stage Queue Pill Indicator (Desktop) */}
              {queue && (
                <div className="hidden lg:block absolute -right-3 top-1/2 -translate-y-1/2 z-20 pointer-events-none">
                  <div className="px-2.5 py-1 rounded-full bg-white border border-slate-300 text-[10px] font-mono tabular-nums text-blue-700 shadow-md flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />
                    <span className="font-semibold">{queue.depth} in queue</span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
