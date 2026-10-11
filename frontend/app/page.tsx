"use client";

import React, { useMemo } from "react";
import { KNOWN_MACHINES } from "../types/factory";
import { useFactoryWebSocket } from "../context/WebSocketContext";
import { MachineCard } from "../components/telemetry/MachineCard";
import { QueueHandoffIndicator } from "../components/telemetry/QueueHandoffIndicator";
import { OEEHeader } from "../components/telemetry/OEEHeader";

interface StageConfig {
  id: "housing" | "casting" | "assembly" | "qc";
  title: string;
  subtitle: string;
  icon: string;
  expectedMachineIds: string[];
}

const STAGES: StageConfig[] = [
  {
    id: "housing",
    title: "1. Housing Sub-Facility",
    subtitle: "Precision polymer molding of outer filter cartridges",
    icon: "🏗️",
    expectedMachineIds: ["hm_01", "hm_02", "hm_03", "hm_04"],
  },
  {
    id: "casting",
    title: "2. Membrane Casting",
    subtitle: "Polymer dope extrusion, phase inversion & film formation",
    icon: "🎞️",
    expectedMachineIds: ["cs_01", "cs_02", "cs_03"],
  },
  {
    id: "assembly",
    title: "3. Assembly Station",
    subtitle: "Membrane insertion, robotic torque fitting & ultrasonic sealing",
    icon: "⚙️",
    expectedMachineIds: ["am_01", "am_02", "am_03"],
  },
  {
    id: "qc",
    title: "4. Quality Control & Testing",
    subtitle: "Automated integrity inspection, leak testing & defect attribution",
    icon: "🔬",
    expectedMachineIds: ["qc_01"],
  },
];

export default function LiveOverviewPage() {
  const { machines, handoffs, status, lastMessageAt } = useFactoryWebSocket();

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

  return (
    <div className="flex flex-col gap-6">
      {/* Live System Status Sub-bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between px-1 py-1 text-xs font-mono text-slate-400 gap-2">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                status === "connected"
                  ? "bg-emerald-400 animate-pulse"
                  : status === "reconnecting"
                  ? "bg-amber-400 animate-ping"
                  : "bg-rose-500"
              }`}
            />
            <span className="uppercase text-slate-200 font-semibold">
              SCADA BUS: {status}
            </span>
          </span>
          <span className="text-slate-600">|</span>
          <span>
            Telemetry Tick:{" "}
            <span className="text-slate-300">
              {lastMessageAt ? new Date(lastMessageAt).toLocaleTimeString() : "Awaiting tick"}
            </span>
          </span>
        </div>

        <div className="flex items-center gap-3 text-slate-400">
          <span>
            Active In-Flight:{" "}
            <strong className="text-cyan-400">{activeInFlightCount} units</strong>
          </span>
          <span className="text-slate-600">|</span>
          <span>
            Buffer Depth Total:{" "}
            <strong className="text-amber-300">
              {handoffs.housingToCasting + handoffs.castingToAssembly + handoffs.assemblyToQc} units
            </strong>
          </span>
        </div>
      </div>

      {/* Evocon OEE Dashboard Header */}
      <OEEHeader machines={machines} />

      {/* Production Stages Pipeline */}
      <div className="flex flex-col gap-6">
        {STAGES.map((stage, idx) => {
          const stageMachines = stage.expectedMachineIds.map(
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

          const activeCount = stageMachines.filter(
            (m) => m.machine_state === "RUNNING" || m.machine_state === "TESTING"
          ).length;
          const stageHasStarved = stageMachines.some((m) => m.starved);

          return (
            <React.Fragment key={stage.id}>
              {/* Stage Container */}
              <section className="scada-panel rounded-xl p-4 lg:p-5 flex flex-col gap-4 border-slate-800">
                {/* Stage Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800/80 gap-2">
                  <div className="flex items-center gap-3">
                    <span className="text-xl p-2 rounded bg-slate-900 border border-slate-800">
                      {stage.icon}
                    </span>
                    <div>
                      <h2 className="text-sm lg:text-base font-bold text-slate-100 font-mono tracking-wide uppercase">
                        {stage.title}
                      </h2>
                      <p className="text-xs text-slate-400">
                        {stage.subtitle}
                      </p>
                    </div>
                  </div>

                  {/* Stage Metrics Badges */}
                  <div className="flex items-center gap-2 font-mono text-xs">
                    <span className="px-2 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-800">
                      {stageMachines.length} {stageMachines.length === 1 ? "Station" : "Stations"}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-500/30">
                      {activeCount} Active
                    </span>
                    {stageHasStarved && (
                      <span className="px-2 py-0.5 rounded bg-amber-950/60 text-amber-400 border border-amber-500/30 animate-pulse">
                        Starved
                      </span>
                    )}
                  </div>
                </div>

                {/* Grid of Machine Status Cards */}
                <div
                  className={`grid grid-cols-1 md:grid-cols-2 ${
                    stage.expectedMachineIds.length >= 4
                      ? "xl:grid-cols-4"
                      : stage.expectedMachineIds.length === 3
                      ? "xl:grid-cols-3"
                      : "xl:grid-cols-2"
                  } gap-3.5`}
                >
                  {stageMachines.map((m) => (
                    <MachineCard key={m.machine_id} machine={m} />
                  ))}
                </div>
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
  );
}
