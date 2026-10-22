"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useFactoryWebSocket } from "../../context/WebSocketContext";
import { isTelemetryMessage } from "../../types/factory";
import { parseQcResultPayload, safeToUpperCase } from "../../lib/plant-utils";

interface EventItem {
  id: string;
  timestamp: string;
  type: "qc_pass" | "qc_fail" | "stage_event" | "telemetry";
  title: string;
  detail: string;
  unitId?: string;
  subFacility?: string;
}

export function LiveEventTicker() {
  const { subscribeToTelemetry, selectedPlantId } = useFactoryWebSocket();
  const [events, setEvents] = useState<EventItem[]>([]);

  useEffect(() => {
    setEvents([]);
  }, [selectedPlantId]);

  useEffect(() => {
    const unsubscribe = subscribeToTelemetry((msg) => {
      const topic = msg.topic || "";
      if (topic.startsWith("plants/") && !topic.startsWith(`plants/${selectedPlantId}/`)) {
        return;
      }
      const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

      if (topic.endsWith("/result") || topic.includes("/qc_result")) {
        const parsedQc = parseQcResultPayload(msg.payload);
        if (parsedQc) {
          const isPass = parsedQc.outcome === "pass";
          setEvents((prev) => [
            {
              id: `${Date.now()}-${Math.random()}`,
              timestamp: now,
              type: isPass ? "qc_pass" : "qc_fail",
              title: isPass ? "QC Verification Passed" : "QC Defect Isolated",
              detail: isPass
                ? `Unit ${parsedQc.unit_id} verified zero integrity defects`
                : `Unit ${parsedQc.unit_id} flagged: ${parsedQc.defect_type || "anomaly"} (${parsedQc.attributed_stage || "upstream"})`,
              unitId: parsedQc.unit_id,
            },
            ...prev.slice(0, 19),
          ]);
        }
      } else if (topic.endsWith("/stage_event")) {
        const rawPayload = (msg.payload || {}) as Record<string, unknown>;
        const inner =
          rawPayload.payload && typeof rawPayload.payload === "object"
            ? (rawPayload.payload as Record<string, unknown>)
            : rawPayload;

        const unitId =
          (inner.unit_id as string) || (rawPayload.unit_id as string) || "unknown";
        const subFacility =
          (inner.area_code as string) ||
          (inner.sub_facility as string) ||
          (rawPayload.sub_facility as string) ||
          "Station";
        const machineId =
          (inner.machine_code as string) ||
          (inner.machine_id as string) ||
          (rawPayload.machine_id as string) ||
          (rawPayload.asset_id as string) ||
          "";
        const outcome =
          (inner.outcome as string) || (rawPayload.outcome as string) || "ok";

        setEvents((prev) => [
          {
            id: `${Date.now()}-${Math.random()}`,
            timestamp: now,
            type: "stage_event",
            title: `Stage Completed: ${subFacility}`,
            detail: `Unit ${unitId} exited ${machineId} (outcome: ${outcome})`,
            unitId: unitId,
            subFacility: subFacility,
          },
          ...prev.slice(0, 19),
        ]);
      } else if (isTelemetryMessage(msg)) {
        const rawPayload = (msg.payload || {}) as Record<string, unknown>;
        const inner =
          rawPayload.payload && typeof rawPayload.payload === "object"
            ? (rawPayload.payload as Record<string, unknown>)
            : rawPayload;
        const isStarved = Boolean(inner.is_starved || rawPayload.starved);

        if (isStarved) {
          const parts = topic.split("/");
          const machineId =
            (inner.machine_code as string) ||
            (rawPayload.machine_id as string) ||
            (rawPayload.asset_id as string) ||
            (parts.length >= 5 ? parts[3] : parts[2]) ||
            "";

          setEvents((prev) => {
            if (
              machineId &&
              prev.length > 0 &&
              prev[0].title.includes(machineId) &&
              prev[0].detail.includes("Starved")
            ) {
              return prev;
            }
            return [
              {
                id: `${Date.now()}-${Math.random()}`,
                timestamp: now,
                type: "telemetry",
                title: `Station Starved: ${safeToUpperCase(machineId, "STATION")}`,
                detail: `Machine waiting for upstream queue buffer delivery`,
              },
              ...prev.slice(0, 19),
            ];
          });
        }
      }
    });

    return () => {
      unsubscribe();
    };
  }, [subscribeToTelemetry, selectedPlantId]);

  return (
    <div className="bg-white border border-slate-200/90 rounded-3xl p-6 lg:p-7 shadow-xs flex flex-col gap-4 transition-all">
      {/* Feed Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-500 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-600" />
          </span>
          <h3 className="text-base font-bold text-slate-900 tracking-tight">
            Live Factory Floor Event Stream
          </h3>
          <span className="text-xs text-slate-500 hidden sm:inline">
            (Real-Time Material & Quality Bus)
          </span>
        </div>
        <span className="text-[11px] font-mono text-slate-500">
          {events.length} live events
        </span>
      </div>

      {/* Events List */}
      {events.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {events.slice(0, 6).map((e, idx) => {
            let badgeBg = "bg-blue-50 text-blue-700 border-blue-200 font-semibold";
            let dotColor = "bg-blue-600";
            let typeLabel = "Process";

            if (e.type === "qc_pass") {
              badgeBg = "bg-emerald-50 text-emerald-700 border-emerald-200 font-semibold";
              dotColor = "bg-emerald-500";
              typeLabel = "QC Pass";
            } else if (e.type === "qc_fail") {
              badgeBg = "bg-rose-50 text-rose-700 border-rose-200 font-semibold";
              dotColor = "bg-rose-500";
              typeLabel = "QC Defect";
            } else if (e.type === "stage_event") {
              badgeBg = "bg-indigo-50 text-indigo-700 border-indigo-200 font-semibold";
              dotColor = "bg-indigo-500";
              typeLabel = "Handoff";
            } else if (e.type === "telemetry") {
              badgeBg = "bg-amber-50 text-amber-800 border-amber-200 font-semibold";
              dotColor = "bg-amber-500";
              typeLabel = "Starved";
            }

            return (
              <div
                key={`${e.id}-${idx}`}
                className="bg-slate-50/70 rounded-2xl p-3.5 flex flex-col justify-between border border-slate-200 hover:border-slate-300 hover:bg-white transition-all shadow-2xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`w-2 h-2 rounded-full ${dotColor} shrink-0`} />
                    <span className="text-xs font-semibold text-slate-900 tracking-tight truncate">
                      {e.title}
                    </span>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badgeBg}`}>
                    {typeLabel}
                  </span>
                </div>

                <p className="text-[11px] text-slate-600 mt-2 leading-relaxed">
                  {e.detail}
                </p>

                <div className="mt-2.5 pt-2 border-t border-slate-200/80 flex items-center justify-between text-[11px]">
                  <span className="font-mono text-slate-500">{e.timestamp}</span>
                  {e.unitId ? (
                    <Link
                      href={`/units/${encodeURIComponent(e.unitId)}`}
                      className="text-blue-600 hover:text-blue-800 font-semibold font-mono"
                    >
                      {e.unitId} →
                    </Link>
                  ) : (
                    <span className="text-slate-400 text-[10px]">Floor Notice</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="p-8 text-center text-xs text-slate-500 bg-slate-50 rounded-2xl border border-slate-200">
          Listening to SCADA event telemetry stream. Events populate as stages complete and units are inspected.
        </div>
      )}
    </div>
  );
}
