"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useFactoryWebSocket } from "../../context/WebSocketContext";
import { isTelemetryMessage } from "../../types/factory";

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
  const { subscribeToTelemetry } = useFactoryWebSocket();
  const [events, setEvents] = useState<EventItem[]>([]);

  useEffect(() => {
    const unsubscribe = subscribeToTelemetry((msg) => {
      const topic = msg.topic || "";
      const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

      if (topic.endsWith("/result")) {
        const payload = msg.payload as {
          unit_id: string;
          outcome: "pass" | "fail";
          defect_type?: string;
          attributed_stage?: string;
        };
        const isPass = payload.outcome === "pass";

        setEvents((prev) => [
          {
            id: `${Date.now()}-${Math.random()}`,
            timestamp: now,
            type: isPass ? "qc_pass" : "qc_fail",
            title: isPass ? "QC Verification Passed" : "QC Defect Isolated",
            detail: isPass
              ? `Unit ${payload.unit_id} verified zero integrity defects`
              : `Unit ${payload.unit_id} flagged: ${payload.defect_type || "anomaly"} (${payload.attributed_stage || "upstream"})`,
            unitId: payload.unit_id,
          },
          ...prev.slice(0, 19),
        ]);
      } else if (topic.endsWith("/stage_event")) {
        const payload = msg.payload as {
          unit_id: string;
          sub_facility: string;
          machine_id: string;
          outcome?: string;
        };
        setEvents((prev) => [
          {
            id: `${Date.now()}-${Math.random()}`,
            timestamp: now,
            type: "stage_event",
            title: `Stage Completed: ${payload.sub_facility}`,
            detail: `Unit ${payload.unit_id} exited ${payload.machine_id} (outcome: ${payload.outcome || "ok"})`,
            unitId: payload.unit_id,
            subFacility: payload.sub_facility,
          },
          ...prev.slice(0, 19),
        ]);
      } else if (isTelemetryMessage(msg)) {
        const payload = msg.payload;
        if (payload.starved) {
          const parts = topic.split("/");
          const machineId = parts[2] || payload.machine_id;
          setEvents((prev) => {
            if (prev.length > 0 && prev[0].title.includes(machineId) && prev[0].detail.includes("Starved")) {
              return prev;
            }
            return [
              {
                id: `${Date.now()}-${Math.random()}`,
                timestamp: now,
                type: "telemetry",
                title: `Station Starved: ${machineId.toUpperCase()}`,
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
  }, [subscribeToTelemetry]);

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
