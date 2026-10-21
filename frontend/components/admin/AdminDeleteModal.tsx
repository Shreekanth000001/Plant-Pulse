"use client";

import React, { useState } from "react";
import { canConfirmDelete } from "../../lib/admin-api";

export interface AdminDeleteModalProps {
  isOpen: boolean;
  isDeleting: boolean;
  plantId: string;
  plantName: string;
  isSystemPlant: boolean;
  error?: string | null;
  onConfirm: () => void;
  onClose: () => void;
}

export function AdminDeleteModal({
  isOpen,
  isDeleting,
  plantId,
  plantName,
  isSystemPlant,
  error,
  onConfirm,
  onClose,
}: AdminDeleteModalProps) {
  const [typedId, setTypedId] = useState("");

  if (!isOpen) return null;

  const handleClose = () => {
    setTypedId("");
    onClose();
  };

  const handleConfirm = () => {
    setTypedId("");
    onConfirm();
  };

  const canConfirm = canConfirmDelete(plantId, typedId, isSystemPlant);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs"
    >
      <div className="bg-white rounded-3xl max-w-lg w-full p-6 sm:p-8 shadow-2xl border-2 border-rose-500/20 flex flex-col gap-6 animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-start justify-between gap-4 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <span className="w-10 h-10 rounded-2xl bg-rose-100 text-rose-700 flex items-center justify-center text-xl shrink-0 font-bold">
              🗑️
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h2
                  id="delete-modal-title"
                  className="text-base sm:text-lg font-bold text-slate-900 tracking-tight"
                >
                  Delete Plant Facility
                </h2>
                {isSystemPlant && (
                  <span className="px-2 py-0.5 rounded-full bg-slate-100 border border-slate-300 text-slate-700 font-semibold text-3xs uppercase tracking-wide">
                    System Plant (Protected)
                  </span>
                )}
              </div>
              <p className="text-2xs sm:text-xs text-slate-500 mt-0.5">
                Permanent deletion of facility definition and data.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={isDeleting}
            className="text-slate-400 hover:text-slate-600 text-lg leading-none p-1 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-40"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {error && (
          <div
            role="alert"
            className="p-3.5 rounded-2xl bg-rose-50 border border-rose-200 text-rose-900 text-xs flex items-start gap-2.5"
          >
            <span className="font-bold text-rose-600 leading-none">✕</span>
            <span>{error}</span>
          </div>
        )}

        {isSystemPlant ? (
          <div className="flex flex-col gap-4 text-xs text-slate-700">
            <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200 flex flex-col gap-2">
              <p className="font-semibold text-slate-900">
                Plant &quot;{plantName}&quot; (<code className="font-mono text-slate-800">{plantId}</code>) is a protected system facility.
              </p>
              <p className="text-slate-500 text-2xs">
                System plants provide baseline reference architectures and active simulated telemetry. They cannot be deleted through the admin console.
              </p>
            </div>
            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={handleClose}
                className="px-5 py-2 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4 text-xs text-slate-700">
            <p>
              Are you sure you want to permanently delete <strong>{plantName}</strong> (<code className="font-mono text-slate-900">{plantId}</code>)?
            </p>

            <div className="p-3.5 rounded-2xl bg-rose-50 border border-rose-200 text-rose-900 text-2xs flex items-start gap-2.5">
              <span className="font-bold text-rose-600 leading-none">!</span>
              <span>
                <strong>Warning:</strong> This action is irreversible. All device credentials, topology definitions, and historical telemetry data for this plant will be permanently removed. Connected MQTT devices will be immediately disconnected.
              </span>
            </div>

            <div className="flex flex-col gap-1.5 pt-2">
              <label htmlFor="confirm-delete-input" className="text-xs font-semibold text-slate-800">
                To confirm, type <span className="font-mono font-bold text-rose-700">{plantId}</span> below:
              </label>
              <input
                id="confirm-delete-input"
                type="text"
                autoComplete="off"
                value={typedId}
                onChange={(e) => setTypedId(e.target.value)}
                placeholder={plantId}
                disabled={isDeleting}
                className="px-3.5 py-2 text-xs font-mono rounded-xl border border-slate-300 focus:outline-hidden focus:ring-2 focus:ring-rose-500/20 focus:border-rose-500 transition-all bg-white text-slate-900 placeholder:text-slate-300"
              />
            </div>

            <div className="pt-3 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={handleClose}
                disabled={isDeleting}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-900 rounded-xl hover:bg-slate-100 transition-colors cursor-pointer disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={!canConfirm || isDeleting}
                className="px-5 py-2 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 disabled:opacity-40 disabled:hover:bg-rose-600 rounded-xl transition-all shadow-sm hover:shadow cursor-pointer flex items-center gap-2"
              >
                {isDeleting ? (
                  <>
                    <span className="animate-spin text-sm">🔄</span>
                    <span>Deleting Plant...</span>
                  </>
                ) : (
                  <span>Delete Plant</span>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
