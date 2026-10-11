"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useFactoryWebSocket } from "../../context/WebSocketContext";

interface HeaderProps {
  onToggleSidebar?: () => void;
}

export function Header({ onToggleSidebar }: HeaderProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { status, reconnectAttempt } = useFactoryWebSocket();
  const [unitSearch, setUnitSearch] = useState("");
  const [currentTime, setCurrentTime] = useState<string>("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(
        now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
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
    <header className="sticky top-0 z-30 w-full border-b border-slate-200/80 bg-white/90 backdrop-blur-md px-4 lg:px-8 py-3 transition-colors shadow-xs">
      <div className="flex items-center justify-between gap-3.5 max-w-7xl mx-auto">
        {/* Left: Mobile hamburger & section breadcrumb */}
        <div className="flex items-center gap-3">
          {onToggleSidebar && (
            <button
              onClick={onToggleSidebar}
              className="lg:hidden p-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 cursor-pointer transition-colors"
              title="Toggle Navigation Menu"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          )}

          {/* Location Breadcrumb */}
          <div className="hidden sm:flex items-center gap-2 text-xs">
            <span className="text-slate-500 font-medium">PlantPulse</span>
            <span className="text-slate-300">/</span>
            <span className="font-semibold text-slate-900">
              {pathname === "/"
                ? "Floor Overview"
                : pathname.startsWith("/units")
                ? "Unit Traceability"
                : "Quality Analytics"}
            </span>
          </div>
        </div>

        {/* Center: Navigation Tabs */}
        <nav className="hidden md:flex items-center p-1 rounded-xl bg-slate-100 border border-slate-200 shadow-inner">
          <Link
            href="/"
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 ${
              isNavActive("/")
                ? "bg-white text-slate-900 shadow-xs border border-slate-200/80 font-semibold"
                : "text-slate-600 hover:text-slate-900 hover:bg-white/60"
            }`}
          >
            <svg className="w-3.5 h-3.5 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
            </svg>
            <span>Live Overview</span>
          </Link>
          <Link
            href="/units"
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 ${
              isNavActive("/units")
                ? "bg-white text-slate-900 shadow-xs border border-slate-200/80 font-semibold"
                : "text-slate-600 hover:text-slate-900 hover:bg-white/60"
            }`}
          >
            <svg className="w-3.5 h-3.5 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
            </svg>
            <span>Unit Traceability</span>
          </Link>
          <Link
            href="/analytics"
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 ${
              isNavActive("/analytics")
                ? "bg-white text-slate-900 shadow-xs border border-slate-200/80 font-semibold"
                : "text-slate-600 hover:text-slate-900 hover:bg-white/60"
            }`}
          >
            <svg className="w-3.5 h-3.5 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <span>Quality Analytics</span>
          </Link>
        </nav>

        {/* Right: Search, Connection Status & Clock */}
        <div className="flex items-center gap-3">
          <form onSubmit={handleSearchSubmit} className="relative flex items-center">
            <label htmlFor="header-unit-search" className="sr-only">
              Search unit serial number
            </label>
            <svg
              className="w-3.5 h-3.5 text-slate-400 absolute left-3 pointer-events-none"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              id="header-unit-search"
              type="text"
              placeholder="Search serial (e.g. unit_...)"
              value={unitSearch}
              onChange={(e) => setUnitSearch(e.target.value)}
              className="bg-white border-2 border-slate-300 rounded-full pl-9 pr-8 py-1.5 text-xs font-medium text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 w-44 lg:w-56 transition-all duration-150 shadow-2xs"
            />
            <span className="absolute right-2.5 px-1.5 py-0.5 rounded text-[10px] font-mono text-slate-600 bg-slate-100 border border-slate-300">
              ⏎
            </span>
          </form>

          {/* Connection status pill */}
          <div className="flex items-center">
            {status === "connected" && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-xs font-semibold text-emerald-700">
                <span className="w-2 h-2 rounded-full bg-emerald-500 ring-2 ring-emerald-200" />
                <span className="hidden sm:inline">Sync Live</span>
              </div>
            )}
            {status === "reconnecting" && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-xs font-semibold text-amber-700">
                <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
                <span className="hidden sm:inline">Reconnecting ({reconnectAttempt})</span>
              </div>
            )}
            {status === "disconnected" && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-50 border border-rose-200 text-xs font-semibold text-rose-700">
                <span className="w-2 h-2 rounded-full bg-rose-500" />
                <span className="hidden sm:inline">Offline</span>
              </div>
            )}
          </div>

          {currentTime && (
            <div className="hidden xl:flex items-center gap-1.5 text-xs text-slate-600 font-mono px-3 py-1.5 bg-slate-100 rounded-full border border-slate-200">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              <span>{currentTime}</span>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
