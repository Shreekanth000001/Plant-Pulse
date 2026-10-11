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
  const isPass = item.outcome === "pass";

  useEffect(() => {
    // Keep failure alerts visible for 15s to allow reading root cause attribution; 6s for passes
    const displayDuration = isPass ? 6000 : 15000;
    const timer = setTimeout(() => {
      onDismiss(item.id);
    }, displayDuration);
    return () => clearTimeout(timer);
  }, [item.id, isPass, onDismiss]);

  return (
    <div
      role={isPass ? "status" : "alert"}
      aria-live={isPass ? "polite" : "assertive"}
      className={`rounded-2xl p-3.5 w-80 shadow-xl border transition-all animate-in slide-in-from-top duration-200 ${
        isPass
          ? "border-emerald-200 bg-white text-slate-900"
          : "border-rose-300 bg-rose-50 text-rose-950"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              isPass ? "bg-emerald-500" : "bg-rose-600 animate-ping"
            }`}
          />
          <span className="font-mono text-xs font-bold uppercase tracking-wider text-slate-600">
            QC Test Event
          </span>
        </div>

        <button
          onClick={() => onDismiss(item.id)}
          className="text-slate-400 hover:text-slate-600 text-xs p-0.5 cursor-pointer"
          aria-label="Dismiss notification"
        >
          ✕
        </button>
      </div>

      <div className="mt-2 flex items-baseline justify-between font-mono">
        <Link
          href={`/units/${item.unit_id}`}
          className="text-xs font-bold text-blue-600 hover:underline flex items-center gap-1"
        >
          {item.unit_id}
          <svg className="w-3 h-3 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </Link>

        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border ${
            isPass ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-rose-100 text-rose-700 border-rose-300"
          }`}
        >
          {item.outcome.toUpperCase()}
        </span>
      </div>

      {!isPass && item.defect_type && (
        <div className="mt-1 text-[11px] text-rose-900 font-medium">
          <span className="font-mono text-rose-700 font-bold">Defect:</span> {item.defect_type}
          {item.attributed_stage && (
            <span className="block text-[10px] text-rose-700 font-mono mt-0.5">
              Attributed Stage: {item.attributed_stage}
            </span>
          )}
        </div>
      )}

      <div className="mt-1.5 text-[9px] font-mono text-slate-400 text-right">
        {item.timestamp}
      </div>
    </div>
  );
}

export function QCAlertToastContainer() {
  const { recentQcResults, dismissNotification } = useFactoryWebSocket();

  if (recentQcResults.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="Quality Control Real-Time Alerts"
      className="fixed top-16 right-4 z-50 flex flex-col gap-2 pointer-events-auto max-h-[calc(100vh-5rem)] overflow-hidden"
    >
      {recentQcResults.map((item, idx) => (
        <ToastItem key={`${item.id}-${idx}`} item={item} onDismiss={dismissNotification} />
      ))}
    </div>
  );
}
