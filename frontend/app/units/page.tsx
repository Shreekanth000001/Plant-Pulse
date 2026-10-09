"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const SAMPLE_UNITS = [
  { id: "unit_000001", status: "passed", stageCount: 3, note: "Full line complete" },
  { id: "unit_000002", status: "passed", stageCount: 3, note: "Full line complete" },
  { id: "unit_000003", status: "passed", stageCount: 3, note: "Full line complete" },
  { id: "unit_000004", status: "passed", stageCount: 3, note: "Full line complete" },
  { id: "unit_000005", status: "passed", stageCount: 3, note: "Full line complete" },
  { id: "unit_000006", status: "passed", stageCount: 3, note: "Full line complete" },
  { id: "unit_000010", status: "in_progress", stageCount: 2, note: "In active transit" },
];

export default function UnitsIndexPage() {
  const router = useRouter();
  const [searchTerm, setSearchTerm] = useState("");

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchTerm.trim()) return;
    router.push(`/units/${encodeURIComponent(searchTerm.trim())}`);
  };

  return (
    <div className="max-w-4xl mx-auto flex flex-col gap-6 py-4">
      {/* Search Header Hero */}
      <div className="scada-panel rounded-xl p-6 md:p-8 flex flex-col gap-4 border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-3 rounded-lg bg-cyan-950/60 border border-cyan-500/40 text-cyan-400 text-2xl font-mono">
            🔍
          </div>
          <div>
            <h1 className="text-xl md:text-2xl font-bold font-mono text-slate-100 uppercase tracking-wide">
              Unit Traceability & Quality Lookup
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Query complete end-to-end manufacturing genealogies, process sensor snapshots, anomaly scores, and root-cause QC defect attribution.
            </p>
          </div>
        </div>

        {/* Search Input Box */}
        <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-2 mt-4">
          <div className="relative flex-1">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Enter Unit Serial Number (e.g. unit_000001)..."
              className="w-full px-4 py-3 bg-slate-950 rounded-lg border border-slate-700 font-mono text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 text-sm"
              autoFocus
            />
          </div>
          <button
            type="submit"
            className="px-6 py-3 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-mono font-bold text-sm transition-colors flex items-center justify-center gap-2 cursor-pointer shadow-[0_0_15px_rgba(6,182,212,0.3)]"
          >
            <span>TRACE UNIT</span>
            <span>➔</span>
          </button>
        </form>
      </div>

      {/* Quick Select Recent Units */}
      <div className="scada-panel rounded-xl p-6 border-slate-800 flex flex-col gap-4">
        <div className="flex items-center justify-between pb-2 border-b border-slate-800">
          <h2 className="text-sm font-bold font-mono text-slate-300 uppercase tracking-wider">
            Quick Lookup & Recent Manufactured Units
          </h2>
          <span className="text-xs font-mono text-slate-500">
            Click to inspect timeline
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          {SAMPLE_UNITS.map((u) => (
            <Link
              key={u.id}
              href={`/units/${u.id}`}
              className="bg-slate-950/70 border border-slate-800 hover:border-cyan-500/50 rounded-lg p-3.5 flex flex-col justify-between group transition-all"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm font-semibold text-cyan-400 group-hover:text-cyan-300">
                  {u.id}
                </span>
                <span
                  className={`text-[10px] font-mono px-1.5 py-0.5 rounded uppercase border ${
                    u.status === "passed"
                      ? "bg-emerald-950/60 text-emerald-400 border-emerald-500/30"
                      : u.status === "failed"
                      ? "bg-rose-950/60 text-rose-400 border-rose-500/30"
                      : "bg-slate-800 text-slate-400 border-slate-700"
                  }`}
                >
                  {u.status}
                </span>
              </div>

              <div className="mt-3 flex items-center justify-between text-xs text-slate-400 font-mono">
                <span>Stages: {u.stageCount} / 4</span>
                <span className="text-[11px] text-slate-500">{u.note}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
