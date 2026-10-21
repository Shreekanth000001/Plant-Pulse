"use client";

import React, { useState } from "react";

interface AdminTokenEntryCardProps {
  onSubmit: (token: string) => Promise<void>;
  error?: string | null;
  isSubmitting?: boolean;
  lockoutSeconds?: number | null;
}

export function AdminTokenEntryCard({
  onSubmit,
  error,
  isSubmitting = false,
  lockoutSeconds = null,
}: AdminTokenEntryCardProps) {
  const [tokenInput, setTokenInput] = useState("");
  const [showToken, setShowToken] = useState(false);

  const isLockedOut = typeof lockoutSeconds === "number" && lockoutSeconds > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLockedOut || isSubmitting) return;
    const trimmed = tokenInput.trim();
    if (!trimmed) return;
    await onSubmit(trimmed);
  };

  return (
    <div
      role="region"
      aria-labelledby="admin-auth-heading"
      className="max-w-xl mx-auto my-8 bg-white rounded-3xl p-6 sm:p-8 border-2 border-slate-300 shadow-md flex flex-col gap-6"
    >
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-5 border-b border-slate-100">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-slate-900 text-white flex items-center justify-center text-xl font-bold shrink-0 shadow-xs">
            ⚙️
          </div>
          <div>
            <h2
              id="admin-auth-heading"
              className="text-base sm:text-lg font-bold text-slate-900 tracking-tight"
            >
              PlantPulse Administration
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Enter the master <code className="font-mono font-semibold text-slate-700">ADMIN_TOKEN</code> to access administrative controls.
            </p>
          </div>
        </div>
        <span className="px-3 py-1 rounded-full bg-slate-100 text-slate-800 border border-slate-200 text-xs font-mono font-semibold whitespace-nowrap">
          Admin Portal
        </span>
      </div>

      {isLockedOut && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-amber-50 border border-amber-300 text-amber-900 text-xs flex items-center gap-3 font-medium"
        >
          <span className="text-amber-700 font-bold text-base">⏳</span>
          <div>
            <p className="font-semibold">Endpoint Throttled (HTTP 429)</p>
            <p className="mt-0.5 text-amber-800">
              Too many failed authentication attempts. Please wait{" "}
              <span className="font-mono font-bold">{lockoutSeconds}s</span> before retrying.
            </p>
          </div>
        </div>
      )}

      {error && !isLockedOut && (
        <div
          role="alert"
          className="p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center gap-2.5 font-medium"
        >
          <span className="text-rose-600 font-bold text-sm">✕</span>
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="relative">
          <input
            id="admin-token-input"
            type={showToken ? "text" : "password"}
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Enter master admin token..."
            aria-label="Master admin token"
            autoComplete="off"
            spellCheck="false"
            required
            disabled={isLockedOut || isSubmitting}
            className="w-full px-4 py-3 pr-20 text-xs sm:text-sm rounded-xl border border-slate-300 bg-slate-50/50 text-slate-900 placeholder:text-slate-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 font-mono transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          />
          <button
            type="button"
            onClick={() => setShowToken((prev) => !prev)}
            disabled={isLockedOut || isSubmitting}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-700 px-2 py-1 rounded cursor-pointer select-none disabled:opacity-50"
            aria-label={showToken ? "Hide token" : "Show token"}
          >
            {showToken ? "Hide" : "Show"}
          </button>
        </div>

        <button
          type="submit"
          disabled={!tokenInput.trim() || isSubmitting || isLockedOut}
          className="w-full px-5 py-3 rounded-xl bg-slate-900 hover:bg-slate-800 active:bg-black text-white font-semibold text-xs sm:text-sm transition-all shadow-xs disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer flex items-center justify-center gap-2"
        >
          {isSubmitting ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Verifying token...</span>
            </>
          ) : (
            <>
              <span>Authenticate &amp; Access Admin Console</span>
              <span aria-hidden="true">&rarr;</span>
            </>
          )}
        </button>
      </form>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between text-2xs text-slate-400 pt-2 border-t border-slate-100 gap-2">
        <span className="flex items-center gap-1.5">
          <span className="text-slate-500">🛡</span>
          Master token is held in React memory only and cleared on page reload or sign out.
        </span>
        <span className="font-mono">Slice 1: Read-Only</span>
      </div>
    </div>
  );
}
