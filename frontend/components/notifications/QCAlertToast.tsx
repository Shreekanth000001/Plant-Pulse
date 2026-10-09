"use client";

import React, { useEffect } from "react";
import Link from "next/link";
import { useFactoryWebSocket, QCNotification } from "../../context/WebSocketContext";

function ToastItem({
  item,
  onDismiss,
}: {
  item: QCNotification;
  onDismiss: (id: string) => void;
}) {
  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss(item.id);
    }, 6000);
    return () => clearTimeout(timer);
  }, [item.id, onDismiss]);

  const isPass = item.outcome === "pass";

  return (
    <div
      className={`scada-panel rounded-lg p-3 w-80 shadow-2xl border transition-all animate-in slide-in-from-top duration-200 ${
        isPass
          ? "border-emerald-500/40 bg-slate-950/95"
          : "border-rose-500/60 bg-rose-950/90 text-rose-100"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              isPass ? "bg-emerald-400" : "bg-rose-500 animate-ping"
            }`}
          />
          <span className="font-mono text-xs font-bold uppercase tracking-wider text-slate-300">
            QC Test Event
          </span>
        </div>

        <button
          onClick={() => onDismiss(item.id)}
          className="text-slate-400 hover:text-slate-200 text-xs p-0.5"
          aria-label="Dismiss notification"
        >
          ✕
        </button>
      </div>

      <div className="mt-2 flex items-baseline justify-between font-mono">
        <Link
          href={`/units/${item.unit_id}`}
          className="text-xs font-semibold text-cyan-400 hover:underline flex items-center gap-1"
        >
          {item.unit_id}
          <svg className="w-3 h-3 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </Link>

        <span
          className={`px-1.5 py-0.2 rounded text-[11px] font-bold uppercase ${
            isPass ? "text-emerald-400" : "text-rose-400 font-extrabold"
          }`}
        >
          {item.outcome.toUpperCase()}
        </span>
      </div>

      {!isPass && item.defect_type && (
        <div className="mt-1 text-[11px] text-rose-200">
          <span className="font-mono text-rose-400 font-medium">Defect:</span> {item.defect_type}
          {item.attributed_stage && (
            <span className="block text-[10px] text-rose-300/80 font-mono">
              Stage: {item.attributed_stage}
            </span>
          )}
        </div>
      )}

      <div className="mt-1.5 text-[9px] font-mono text-slate-500 text-right">
        {item.timestamp}
      </div>
    </div>
  );
}

export function QCAlertToastContainer() {
  const { recentQcResults, dismissNotification } = useFactoryWebSocket();

  if (recentQcResults.length === 0) return null;

  return (
    <div className="fixed top-16 right-4 z-50 flex flex-col gap-2 pointer-events-auto max-h-[calc(100vh-5rem)] overflow-hidden">
      {recentQcResults.map((item) => (
        <ToastItem key={item.id} item={item} onDismiss={dismissNotification} />
      ))}
    </div>
  );
}
