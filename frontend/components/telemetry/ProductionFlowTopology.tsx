"use client";

import React from "react";
import { MachineStatus, QueueHandoffs, KNOWN_MACHINES } from "../../types/factory";

interface ProductionFlowTopologyProps {
  machines: Record<string, MachineStatus>;
  handoffs: QueueHandoffs;
  onSelectMachine: (machineId: string) => void;
}

interface StageFlowConfig {
  id: "housing" | "casting" | "assembly" | "qc";
  name: string;
  stageNum: number;
  iconType: "housing" | "casting" | "assembly" | "qc";
  nominalCycle: string;
  machineIds: string[];
}

function StageIcon({ type }: { type: "housing" | "casting" | "assembly" | "qc" }) {
  if (type === "housing") {
    return (
      <svg className="w-4 h-4 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    );
  }
  if (type === "casting") {
    return (
      <svg className="w-4 h-4 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h18M3 16h18" />
      </svg>
    );
  }
  if (type === "assembly") {
    return (
      <svg className="w-4 h-4 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    );
  }
  return (
    <svg className="w-4 h-4 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  );
}

const FLOW_STAGES: StageFlowConfig[] = [
  {
    id: "housing",
    name: "Housing (Molding)",
    stageNum: 1,
    iconType: "housing",
    nominalCycle: "75s / unit",
    machineIds: ["hm_01", "hm_02", "hm_03", "hm_04"],
  },
  {
    id: "casting",
    name: "Membrane Casting",
    stageNum: 2,
    iconType: "casting",
    nominalCycle: "120s / unit",
    machineIds: ["cs_01", "cs_02", "cs_03"],
  },
  {
    id: "assembly",
    name: "Assembly Station",
    stageNum: 3,
    iconType: "assembly",
    nominalCycle: "50s / unit",
    machineIds: ["am_01", "am_02", "am_03"],
  },
  {
    id: "qc",
    name: "Quality Control",
    stageNum: 4,
    iconType: "qc",
    nominalCycle: "20s / unit",
    machineIds: ["qc_01"],
  },
];

export function ProductionFlowTopology({
  machines,
  handoffs,
  onSelectMachine,
}: ProductionFlowTopologyProps) {
  const getQueueInfo = (idx: number) => {
    if (idx === 0) return { depth: handoffs.housingToCasting, from: "Housing", to: "Casting" };
    if (idx === 1) return { depth: handoffs.castingToAssembly, from: "Casting", to: "Assembly" };
    if (idx === 2) return { depth: handoffs.assemblyToQc, from: "Assembly", to: "QC" };
    return null;
  };

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
              <span>Facility Line Floor Flow Topology</span>
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                Interactive Line Balance
              </span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Real-time material flow across production stations, dynamic buffer capacities, and station pacing.
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
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 items-stretch relative">
        {FLOW_STAGES.map((stage, idx) => {
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
                    <span className="p-2 rounded-xl bg-white border border-slate-200 shadow-xs flex items-center justify-center">
                      <StageIcon type={stage.iconType} />
                    </span>
                    <div>
                      <div className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                        <span>{stage.name}</span>
                      </div>
                      <div className="text-[10px] text-slate-500 font-mono">
                        Cycle: {stage.nominalCycle}
                      </div>
                    </div>
                  </div>

                  <span className="w-6 h-6 rounded-full bg-blue-50 text-blue-700 border border-blue-200 flex items-center justify-center text-xs font-bold font-mono">
                    {stage.stageNum}
                  </span>
                </div>

                {/* Stations Pucks in this stage */}
                <div className="my-3 flex flex-col gap-2">
                  <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                    Assigned Stations ({stage.machineIds.length})
                  </div>
                  <div className="grid grid-cols-1 gap-2">
                    {stage.machineIds.map((machineId) => {
                      const m = machines[machineId];
                      const meta = KNOWN_MACHINES[machineId];
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
                                {meta?.name || machineId}
                              </div>
                              <div className="text-[10px] font-mono text-slate-500 truncate">
                                {hasUnit ? (
                                  <span className="text-blue-600 font-medium">Unit: {m.current_unit_id}</span>
                                ) : (
                                  <span className="text-slate-400 italic">Empty • {state.toLowerCase()}</span>
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
                    Active: <strong className="text-emerald-700 font-mono font-semibold">{runningCount}</strong>
                  </span>
                  <span>
                    Starved: <strong className={starvedCount > 0 ? "text-amber-700 font-mono font-semibold" : "text-slate-500 font-mono"}>{starvedCount}</strong>
                  </span>
                  <span>
                    Fault: <strong className={faultCount > 0 ? "text-rose-600 font-mono font-bold" : "text-slate-500 font-mono"}>{faultCount}</strong>
                  </span>
                </div>
              </div>

              {/* Mobile Inter-Stage Buffer Pill */}
              {queue && (
                <div className="lg:hidden flex items-center justify-center -my-1 py-1">
                  <div className="px-3 py-1 rounded-full bg-slate-50 border border-slate-300 text-[11px] font-mono text-blue-700 shadow-2xs flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />
                    <span className="font-semibold">{queue.from} ➔ {queue.to}: {queue.depth} in buffer</span>
                  </div>
                </div>
              )}

              {/* Inter-Stage Queue Pill Indicator (Desktop) */}
              {queue && (
                <div className="hidden lg:block absolute -right-3 top-1/2 -translate-y-1/2 z-20 pointer-events-none">
                  <div className="px-2.5 py-1 rounded-full bg-white border border-slate-300 text-[10px] font-mono text-blue-700 shadow-md flex items-center gap-1.5">
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
