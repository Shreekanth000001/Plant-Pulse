"use client";

import React, { useState } from "react";

interface TokenEntryCardProps {
  plantName: string;
  plantId: string;
  onSubmit: (token: string) => void;
  error?: string | null;
  isSubmitting?: boolean;
}

export function TokenEntryCard({
  plantName,
  plantId,
  onSubmit,
  error,
  isSubmitting = false,
}: TokenEntryCardProps) {
  const [tokenInput, setTokenInput] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = tokenInput.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  return (
    <div
      role="region"
      aria-labelledby="token-auth-heading"
      className="bg-white rounded-3xl p-6 sm:p-8 border-2 border-amber-300 shadow-sm flex flex-col gap-6"
    >
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-5 border-b border-slate-100">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-amber-100 border border-amber-300 flex items-center justify-center text-amber-800 text-xl font-bold shrink-0 shadow-xs">
            🔒
          </div>
          <div>
            <h2
              id="token-auth-heading"
              className="text-base sm:text-lg font-bold text-slate-900 tracking-tight"
            >
              Viewer Authentication Required
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Access to live telemetry and configuration for{" "}
              <strong className="text-slate-800 font-semibold">{plantName || plantId}</strong>{" "}
              is restricted to authorized viewers.
            </p>
          </div>
        </div>
        <span className="px-3 py-1 rounded-full bg-amber-50 text-amber-800 border border-amber-200 text-xs font-mono font-semibold whitespace-nowrap">
          Protected Plant
        </span>
      </div>

      {error && (
        <div
          role="alert"
          className="p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center gap-2.5 font-medium"
        >
          <span className="text-rose-600 font-bold">✕</span>
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <input
            id="viewer-token-input"
            type={showPassword ? "text" : "password"}
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Enter viewer access token..."
            aria-label="Viewer access token"
            autoComplete="off"
            spellCheck="false"
            required
            className="w-full px-4 py-2.5 pr-20 text-xs sm:text-sm rounded-xl border border-slate-300 bg-slate-50/50 text-slate-900 placeholder:text-slate-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400 font-mono transition-all"
          />
          <button
            type="button"
            onClick={() => setShowPassword((prev) => !prev)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-700 px-2 py-1 rounded cursor-pointer select-none"
            aria-label={showPassword ? "Hide token" : "Show token"}
          >
            {showPassword ? "Hide" : "Show"}
          </button>
        </div>

        <button
          type="submit"
          disabled={!tokenInput.trim() || isSubmitting}
          className="px-5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-600 active:bg-amber-700 text-slate-950 font-semibold text-xs sm:text-sm transition-all shadow-xs disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer flex items-center justify-center gap-2"
        >
          {isSubmitting ? (
            <>
              <span className="w-3.5 h-3.5 border-2 border-slate-900/30 border-t-slate-900 rounded-full animate-spin" />
              <span>Authenticating...</span>
            </>
          ) : (
            <>
              <span>Authenticate &amp; View</span>
              <span aria-hidden="true">&rarr;</span>
            </>
          )}
        </button>
      </form>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between text-2xs text-slate-400 pt-2 border-t border-slate-100 gap-2">
        <span className="flex items-center gap-1.5">
          <span className="text-slate-500">🛡</span>
          Credentials are stored in browser session storage only and cleared on disconnect.
        </span>
        <span className="font-mono">Plant: {plantId}</span>
      </div>
    </div>
  );
}
