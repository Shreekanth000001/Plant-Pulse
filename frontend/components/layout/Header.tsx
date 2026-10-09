"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useFactoryWebSocket } from "../../context/WebSocketContext";

export function Header() {
  const pathname = usePathname();
  const router = useRouter();
  const { status, reconnectAttempt } = useFactoryWebSocket();
  const [unitSearch, setUnitSearch] = useState("");
  const [utcTime, setUtcTime] = useState<string>("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setUtcTime(
        now.toISOString().substring(11, 19) + " UTC"
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!unitSearch.trim()) return;
    const clean = unitSearch.trim();
    setUnitSearch("");
    router.push(`/units/${encodeURIComponent(clean)}`);
  };

  const isNavActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-800 bg-[#080c14]/95 backdrop-blur px-4 lg:px-8 py-2.5">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 max-w-7xl mx-auto">
        {/* Brand & Connection Status */}
        <div className="flex items-center gap-4">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="w-8 h-8 rounded bg-cyan-950/80 border border-cyan-500/50 flex items-center justify-center font-mono font-bold text-cyan-400 group-hover:border-cyan-400 transition-colors shadow-[0_0_10px_rgba(6,182,212,0.2)]">
              P⚡P
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold tracking-wider text-sm text-slate-100 uppercase font-mono">
                  PlantPulse
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono border border-slate-700">
                  SCADA v2.4
                </span>
              </div>
              <div className="text-[10px] text-slate-400 font-mono tracking-tight">
                Membrane Manufacturing Line 01
              </div>
            </div>
          </Link>

          {/* Connection Pill */}
          <div className="hidden sm:flex items-center">
            {status === "connected" && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-950/50 border border-emerald-500/30 text-[11px] font-mono text-emerald-300">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_8px_#34d399]" />
                <span>WS LIVE</span>
              </div>
            )}
            {status === "reconnecting" && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-950/50 border border-amber-500/40 text-[11px] font-mono text-amber-300">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
                <span>RECONNECTING ({reconnectAttempt})...</span>
              </div>
            )}
            {status === "disconnected" && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-950/50 border border-rose-500/40 text-[11px] font-mono text-rose-300">
                <span className="w-2 h-2 rounded-full bg-rose-500" />
                <span>OFFLINE</span>
              </div>
            )}
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav className="flex items-center gap-1 text-xs font-mono">
          <Link
            href="/"
            className={`px-3 py-1.5 rounded transition-colors ${
              isNavActive("/")
                ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-semibold"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
            }`}
          >
            LIVE OVERVIEW
          </Link>
          <Link
            href="/units"
            className={`px-3 py-1.5 rounded transition-colors ${
              isNavActive("/units")
                ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-semibold"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
            }`}
          >
            UNIT LOOKUP
          </Link>
          <Link
            href="/analytics"
            className={`px-3 py-1.5 rounded transition-colors ${
              isNavActive("/analytics")
                ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-semibold"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
            }`}
          >
            QUALITY ANALYTICS
          </Link>
        </nav>

        {/* Quick Search & UTC Clock */}
        <div className="flex items-center gap-3">
          <form onSubmit={handleSearchSubmit} className="relative">
            <input
              type="text"
              placeholder="Unit ID (e.g. unit_000001)"
              value={unitSearch}
              onChange={(e) => setUnitSearch(e.target.value)}
              className="bg-slate-900/90 border border-slate-700/80 rounded px-2.5 py-1 text-xs font-mono text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 w-44 lg:w-56"
            />
            <button
              type="submit"
              className="absolute right-1 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded text-[10px] font-mono text-slate-400 hover:text-cyan-400"
              title="Lookup unit"
            >
              ⏎
            </button>
          </form>

          {utcTime && (
            <div className="hidden lg:block font-mono text-[11px] text-slate-500 px-2 py-1 bg-slate-900/60 rounded border border-slate-800">
              {utcTime}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
