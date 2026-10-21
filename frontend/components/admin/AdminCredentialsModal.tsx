"use client";

import React, { useState } from "react";
import type { OneTimeDeviceCredential } from "../../lib/admin-api";

interface AdminCredentialsModalProps {
  isOpen: boolean;
  source: "create" | "rotate" | null;
  credentials: OneTimeDeviceCredential[] | null;
  brokerReloaded?: boolean;
  onClose: () => void;
}

export function AdminCredentialsModal({
  isOpen,
  source,
  credentials,
  brokerReloaded,
  onClose,
}: AdminCredentialsModalProps) {
  const [copied, setCopied] = useState(false);
  const [showPassword, setShowPassword] = useState(true);

  if (!isOpen || !credentials || credentials.length === 0) {
    return null;
  }

  const handleCopy = async () => {
    try {
      const formatted = credentials
        .map(
          (c, idx) =>
            `# Credential ${idx + 1}\nMQTT_USER=${c.username}\nMQTT_PASSWORD=${c.password || ""}\nMQTT_CLIENT_ID=${c.client_id}`
        )
        .join("\n\n");

      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(formatted);
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      }
    } catch {
      // ignore clipboard failures in headless environments
    }
  };

  const title =
    source === "rotate"
      ? "Rotated Device Credentials"
      : "One-Time Initial Device Credentials";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="cred-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs"
    >
      <div className="bg-white rounded-3xl max-w-lg w-full p-6 sm:p-8 shadow-2xl border-2 border-emerald-500/20 flex flex-col gap-6 animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-start justify-between gap-4 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-emerald-50 text-emerald-700 flex items-center justify-center text-lg font-bold">
              🔑
            </div>
            <div>
              <h3
                id="cred-modal-title"
                className="text-base sm:text-lg font-bold text-slate-900 tracking-tight"
              >
                {title}
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Save these credentials now. Plain-text passwords cannot be displayed again.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close modal"
            className="text-slate-400 hover:text-slate-700 p-1 text-sm font-semibold rounded-lg hover:bg-slate-100 transition-colors"
          >
            ✕
          </button>
        </div>

        <div className="p-3.5 rounded-2xl bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-start gap-2.5">
          <span className="font-bold text-base leading-none text-amber-700">⚠️</span>
          <p className="leading-relaxed">
            <strong className="font-semibold">Copy and store securely:</strong> Once you dismiss this dialog, the plain-text password is permanently purged from memory and cannot be recovered.
          </p>
        </div>

        {brokerReloaded === false && (
          <div className="p-3 rounded-xl bg-orange-50 border border-orange-200 text-orange-900 text-xs flex items-center gap-2">
            <span>ℹ️</span>
            <span>Mosquitto reload returned false; broker will pick up changes on next restart.</span>
          </div>
        )}

        <div className="flex flex-col gap-4 max-h-[45vh] overflow-y-auto pr-1">
          {credentials.map((cred, idx) => (
            <div
              key={cred.username + idx}
              className="bg-slate-50 border border-slate-200 rounded-2xl p-4 flex flex-col gap-2.5 font-mono text-xs"
            >
              <div className="flex items-center justify-between text-slate-500 text-[11px] font-sans font-semibold border-b border-slate-200 pb-1.5">
                <span>Credential #{idx + 1}</span>
                <span className="px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-800 text-[10px]">
                  ACTIVE
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500 font-sans text-[11px]">Username:</span>
                <span className="font-semibold text-slate-900 select-all">{cred.username}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500 font-sans text-[11px]">Password:</span>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-emerald-700 select-all">
                    {showPassword ? cred.password || "[NOT SET]" : "••••••••••••••••"}
                  </span>
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-[10px] text-slate-400 hover:text-slate-700 underline font-sans"
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500 font-sans text-[11px]">Client ID:</span>
                <span className="text-slate-700 select-all">{cred.client_id}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between gap-3 pt-4 border-t border-slate-100">
          <button
            type="button"
            onClick={handleCopy}
            className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 border transition-colors ${
              copied
                ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50 hover:border-slate-400"
            }`}
          >
            <span>{copied ? "✓" : "📋"}</span>
            <span>{copied ? "Copied to Clipboard!" : "Copy All Credentials"}</span>
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-5 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold transition-colors shadow-xs"
          >
            I have saved credentials & Close
          </button>
        </div>
      </div>
    </div>
  );
}
