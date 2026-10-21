"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

interface AdminHeaderProps {
  onLogout: () => void;
}

export function AdminHeader({ onLogout }: AdminHeaderProps) {
  const pathname = usePathname();

  return (
    <div className="w-full bg-white border border-slate-200 rounded-2xl p-4 sm:p-5 mb-6 shadow-2xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <Link
          href="/admin"
          className="text-base sm:text-lg font-bold text-slate-900 hover:text-blue-600 transition-colors flex items-center gap-2"
        >
          <span className="w-8 h-8 rounded-xl bg-slate-900 text-white flex items-center justify-center text-sm font-bold shadow-2xs">
            ⚙️
          </span>
          <span>PlantPulse Admin</span>
        </Link>
        <span className="px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 text-2xs font-mono font-semibold uppercase tracking-wider">
          Slice 1: Read-Only
        </span>
      </div>

      <div className="flex items-center gap-3 w-full sm:w-auto justify-between sm:justify-end">
        <div className="flex items-center gap-2 text-2xs text-slate-500 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-xl font-mono">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>Token in React Memory</span>
        </div>

        {pathname !== "/admin" && (
          <Link
            href="/admin"
            className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-xl transition-all"
          >
            &larr; All Plants
          </Link>
        )}

        <button
          type="button"
          onClick={onLogout}
          className="px-3.5 py-1.5 text-xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-xl transition-all cursor-pointer flex items-center gap-1.5"
          title="Clear admin token from memory and lock session"
        >
          <span>🔒</span>
          <span>Lock / Sign Out</span>
        </button>
      </div>
    </div>
  );
}
