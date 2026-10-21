"use client";

import React from "react";
import Link from "next/link";

interface AdminUnmountedScreenProps {
  onRetry?: () => void;
}

export function AdminUnmountedScreen({ onRetry }: AdminUnmountedScreenProps) {
  return (
    <div
      role="region"
      aria-labelledby="unmounted-heading"
      className="max-w-2xl mx-auto my-12 bg-white rounded-3xl p-8 sm:p-10 border border-slate-200 shadow-sm flex flex-col gap-6 text-center items-center"
    >
      <div className="w-16 h-16 rounded-3xl bg-amber-100 border border-amber-300 text-amber-900 flex items-center justify-center text-3xl font-bold shadow-xs">
        ⚠️
      </div>

      <div className="flex flex-col gap-2">
        <h2
          id="unmounted-heading"
          className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight"
        >
          Admin Endpoints Not Mounted
        </h2>
        <p className="text-sm text-slate-600 max-w-lg mx-auto leading-relaxed">
          The backend API is running, but administrative endpoints are disabled (<code className="font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded text-slate-800">MOUNT_ADMIN_ENDPOINTS=false</code>).
        </p>
      </div>

      <div className="w-full bg-slate-50 border border-slate-200 rounded-2xl p-5 text-left flex flex-col gap-3">
        <span className="text-xs font-semibold text-slate-700 tracking-wide uppercase">
          Required Backend Configuration (.env)
        </span>
        <pre className="text-xs font-mono bg-white border border-slate-200 p-3 rounded-xl text-slate-800 overflow-x-auto">
{`MOUNT_ADMIN_ENDPOINTS=true
ADMIN_TOKEN=your_secure_32_character_token_here`}
        </pre>
        <p className="text-2xs text-slate-500">
          After updating environment variables, restart the API container to mount administrative routes at <code className="font-mono">/api/admin/*</code>.
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 w-full sm:w-auto pt-2">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="px-6 py-2.5 rounded-xl border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 font-semibold text-xs transition-all shadow-2xs cursor-pointer"
          >
            Check Status Again
          </button>
        )}
        <Link
          href="/"
          className="px-6 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-semibold text-xs transition-all shadow-xs flex items-center justify-center gap-1.5"
        >
          <span>&larr;</span>
          <span>Return to Live Overview</span>
        </Link>
      </div>
    </div>
  );
}
