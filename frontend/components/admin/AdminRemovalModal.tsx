"use client";

import React from "react";

export interface AdminRemovalModalProps {
  isOpen: boolean;
  isSubmitting: boolean;
  removedAreas: string[];
  removedMachines: string[];
  removedSignals: string[];
  onConfirm: () => void;
  onCancel: () => void;
}

export function AdminRemovalModal({
  isOpen,
  isSubmitting,
  removedAreas,
  removedMachines,
  removedSignals,
  onConfirm,
  onCancel,
}: AdminRemovalModalProps) {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="removal-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs"
    >
      <div className="bg-white rounded-3xl max-w-lg w-full p-6 sm:p-8 shadow-2xl border-2 border-rose-500/20 flex flex-col gap-6 animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-start justify-between gap-4 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <span className="w-10 h-10 rounded-2xl bg-rose-100 text-rose-700 flex items-center justify-center text-xl shrink-0 font-bold">
              ⚠️
            </span>
            <div>
              <h2
                id="removal-modal-title"
                className="text-base sm:text-lg font-bold text-slate-900 tracking-tight"
              >
                Confirm Component Removals
              </h2>
              <p className="text-2xs sm:text-xs text-slate-500 mt-0.5">
                Updating this plant definition will delete existing facility components.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="text-slate-400 hover:text-slate-600 text-lg leading-none p-1 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-40"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-4 text-xs text-slate-700">
          <p className="font-semibold text-slate-900">
            The following components and their historical telemetry will be permanently removed:
          </p>

          <div className="flex flex-col gap-3 p-4 rounded-2xl bg-slate-50 border border-slate-200">
            {removedAreas.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="text-2xs uppercase tracking-wider font-bold text-slate-500">
                  Areas ({removedAreas.length})
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {removedAreas.map((a) => (
                    <span
                      key={a}
                      className="px-2.5 py-1 rounded-lg bg-rose-100 text-rose-800 font-mono text-2xs font-semibold"
                    >
                      {a}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {removedMachines.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="text-2xs uppercase tracking-wider font-bold text-slate-500">
                  Machines ({removedMachines.length})
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {removedMachines.map((m) => (
                    <span
                      key={m}
                      className="px-2.5 py-1 rounded-lg bg-rose-100 text-rose-800 font-mono text-2xs font-semibold"
                    >
                      {m}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {removedSignals.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="text-2xs uppercase tracking-wider font-bold text-slate-500">
                  Signals ({removedSignals.length})
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {removedSignals.map((s) => (
                    <span
                      key={s}
                      className="px-2.5 py-1 rounded-lg bg-rose-100 text-rose-800 font-mono text-2xs font-semibold"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="p-3.5 rounded-2xl bg-amber-50 border border-amber-200 text-amber-900 text-2xs flex items-start gap-2.5">
            <span className="font-bold text-amber-700 text-sm leading-none shrink-0">!</span>
            <span>
              <strong>Permanent Action:</strong> Telemetry data, alerts, and configurations for these
              components cannot be recovered after removal.
            </span>
          </div>
        </div>

        <div className="pt-2 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-900 rounded-xl hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isSubmitting}
            className="px-5 py-2.5 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-xl transition-all shadow-sm hover:shadow cursor-pointer flex items-center gap-2 disabled:opacity-50"
          >
            {isSubmitting ? (
              <>
                <span className="animate-spin text-sm">🔄</span>
                <span>Applying Removals...</span>
              </>
            ) : (
              <span>Confirm &amp; Apply Removals</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
