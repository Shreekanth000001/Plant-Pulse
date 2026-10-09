"use client";

import React, { useEffect, useState, useMemo } from "react";
import { fetchLatestMachines } from "../lib/api";
import { MachineStatus, KNOWN_MACHINES } from "../types/factory";
import { useFactoryWebSocket } from "../context/WebSocketContext";
import { MachineCard } from "../components/telemetry/MachineCard";
import { QueueHandoffIndicator } from "../components/telemetry/QueueHandoffIndicator";

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
  const { subscribeToTelemetry, handoffs, status } = useFactoryWebSocket();
  const [machines, setMachines] = useState<Record<string, MachineStatus>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastTickAt, setLastTickAt] = useState<string | null>(null);

  // 1. Fetch initial machine state on load
  useEffect(() => {
    let isMounted = true;
    async function loadInitial() {
      try {
        setLoading(true);
        const data = await fetchLatestMachines();
        if (!isMounted) return;

        const map: Record<string, MachineStatus> = {};
        for (const m of data) {
          map[m.machine_id] = m;
        }

        // Ensure default records for known machines if not yet in DB
        for (const [id, meta] of Object.entries(KNOWN_MACHINES)) {
          if (!map[id]) {
            map[id] = {
              machine_id: id,
              name: meta.name,
              sub_facility: meta.stage,
              machine_state: "IDLE",
              phase: "IDLE",
              starved: false,
              good_count: 0,
              reject_count: 0,
              extra: {},
            };
          }
        }

        setMachines(map);
        setLoading(false);
      } catch (err: any) {
        if (!isMounted) return;
        setError(err.message || "Failed to load initial machine state");
        setLoading(false);
      }
    }

    loadInitial();
    return () => {
      isMounted = false;
    };
  }, []);

  // 2. Subscribe to WebSocket telemetry updates
  useEffect(() => {
    const unsubscribe = subscribeToTelemetry((msg) => {
      if (!msg.topic || !msg.topic.endsWith("/telemetry")) {
        // As per requirements: only telemetry messages update live machine cards;
        // ignore stage_event/result messages here.
        return;
      }

      const parts = msg.topic.split("/");
      if (parts.length < 4) return;
      const subFacility = parts[1];
      const machineId = parts[2];
      const payload = msg.payload || {};

      setLastTickAt(new Date().toLocaleTimeString());

      setMachines((prev) => {
        const existing = prev[machineId] || {
          machine_id: machineId,
          sub_facility: subFacility,
          name: KNOWN_MACHINES[machineId]?.name || machineId,
          machine_state: "IDLE",
          starved: false,
          extra: {},
        };

        const excluded = new Set([
          "machine_id",
          "name",
          "machine_state",
          "phase",
          "starved",
          "current_unit",
          "current_unit_id",
          "vibration",
          "vibration_wear_level",
          "good_count",
          "reject_count",
          "stage_event",
          "last_result",
        ]);

        const mergedExtra: Record<string, any> = {
          ...(existing.extra || {}),
        };

        for (const [key, value] of Object.entries(payload)) {
          if (!excluded.has(key)) {
            mergedExtra[key] = value;
          }
        }

        const currentUnit =
          payload.current_unit !== undefined
            ? payload.current_unit
            : payload.current_unit_id !== undefined
            ? payload.current_unit_id
            : existing.current_unit_id;

        return {
          ...prev,
          [machineId]: {
            ...existing,
            machine_id: machineId,
            sub_facility: subFacility,
            name: payload.name || existing.name,
            machine_state:
              payload.machine_state || existing.machine_state || "IDLE",
            phase:
              payload.phase !== undefined ? payload.phase : existing.phase,
            starved:
              payload.starved !== undefined
                ? Boolean(payload.starved)
                : existing.starved,
            current_unit_id: currentUnit,
            vibration:
              payload.vibration !== undefined
                ? payload.vibration
                : existing.vibration,
            vibration_wear_level:
              payload.vibration_wear_level !== undefined
                ? payload.vibration_wear_level
                : existing.vibration_wear_level,
            good_count:
              payload.good_count !== undefined
                ? payload.good_count
                : existing.good_count,
            reject_count:
              payload.reject_count !== undefined
                ? payload.reject_count
                : existing.reject_count,
            extra: mergedExtra,
            timestamp: new Date().toISOString(),
          },
        };
      });
    });

    return () => {
      unsubscribe();
    };
  }, [subscribeToTelemetry]);

  // Aggregate stats across all machines
  const stats = useMemo(() => {
    const list = Object.values(machines);
    let running = 0;
    let starved = 0;
    let fault = 0;
    let idle = 0;
    let totalGood = 0;
    let totalReject = 0;

    for (const m of list) {
      const state = m.machine_state?.toUpperCase();
      if (state === "FAULT") fault++;
      else if (m.starved) starved++;
      else if (state === "RUNNING" || state === "TESTING") running++;
      else idle++;

      totalGood += m.good_count ?? 0;
      totalReject += m.reject_count ?? 0;
    }

    return {
      total: list.length,
      running,
      starved,
      fault,
      idle,
      totalGood,
      totalReject,
    };
  }, [machines]);

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

  if (loading && Object.keys(machines).length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3 font-mono">
        <div className="w-8 h-8 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin" />
        <div className="text-xs text-slate-400">
          INITIALIZING SCADA TELEMETRY BUS...
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Top SCADA KPI Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="scada-panel rounded-lg p-3">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Active Stations
          </div>
          <div className="text-xl font-bold font-mono text-slate-100 mt-1">
            {stats.running} / {stats.total}
          </div>
          <div className="text-[10px] text-emerald-400 font-mono mt-0.5">
            Operational
          </div>
        </div>

        <div className="scada-panel rounded-lg p-3">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Starved Machines
          </div>
          <div className={`text-xl font-bold font-mono mt-1 ${stats.starved > 0 ? "text-amber-400" : "text-slate-300"}`}>
            {stats.starved}
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">
            Waiting for input
          </div>
        </div>

        <div className="scada-panel rounded-lg p-3">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Fault Code Alert
          </div>
          <div className={`text-xl font-bold font-mono mt-1 ${stats.fault > 0 ? "text-rose-400" : "text-emerald-400"}`}>
            {stats.fault}
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">
            {stats.fault > 0 ? "Requires technician" : "Zero active faults"}
          </div>
        </div>

        <div className="scada-panel rounded-lg p-3">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Total Good Units
          </div>
          <div className="text-xl font-bold font-mono text-emerald-400 mt-1">
            {stats.totalGood}
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">
            Factory shift total
          </div>
        </div>

        <div className="scada-panel rounded-lg p-3">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Total Flagged
          </div>
          <div className={`text-xl font-bold font-mono mt-1 ${stats.totalReject > 0 ? "text-rose-400" : "text-slate-400"}`}>
            {stats.totalReject}
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">
            Defects isolated
          </div>
        </div>

        <div className="scada-panel rounded-lg p-3">
          <div className="text-[10px] text-slate-500 uppercase font-mono">
            Telemetry Sync
          </div>
          <div className="text-sm font-semibold font-mono text-cyan-400 mt-1 truncate">
            {status.toUpperCase()}
          </div>
          <div className="text-[10px] text-slate-500 font-mono mt-0.5 truncate">
            {lastTickAt ? `Tick: ${lastTickAt}` : "Awaiting tick"}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-amber-950/60 border border-amber-600/50 p-3 rounded-lg text-xs font-mono text-amber-300 flex items-center justify-between">
          <span>⚠️ Notice: {error}. Live stream will resume upon backend availability.</span>
          <button
            onClick={() => window.location.reload()}
            className="px-2 py-0.5 rounded bg-amber-900/60 hover:bg-amber-800 text-amber-200 border border-amber-500/50"
          >
            Retry
          </button>
        </div>
      )}

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
                      {stageMachines.filter((m) => m.machine_state === "RUNNING" || m.machine_state === "TESTING").length} Active
                    </span>
                    {stageMachines.some((m) => m.starved) && (
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
