"use client";

import React, { useState, Suspense } from "react";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { ServerWakeupBanner } from "./ServerWakeupBanner";
import { DemoBudgetBanner } from "./DemoBudgetBanner";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen flex bg-slate-50 text-slate-900 antialiased selection:bg-blue-100 selection:text-blue-900">
      {/* Sleek Modern Left Sidebar */}
      <Suspense fallback={<aside className="fixed top-0 bottom-0 left-0 z-50 w-64 bg-white border-r border-slate-200 hidden lg:block" />}>
        <Sidebar
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />
      </Suspense>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 lg:pl-64 transition-all">
        {/* Top Header */}
        <Suspense fallback={<header className="sticky top-0 z-30 w-full h-16 border-b border-slate-200 bg-white/90" />}>
          <Header onToggleSidebar={() => setSidebarOpen((prev) => !prev)} />
        </Suspense>

        {/* Cold Start Server Wakeup Banner */}
        <ServerWakeupBanner />

        {/* Daily Demo Budget Exhausted Banner */}
        <DemoBudgetBanner />

        {/* Page Body */}
        <main className="flex-1 p-4 lg:p-8 max-w-7xl w-full mx-auto">
          {children}
        </main>

        {/* Modern App Shell Footer */}
        <footer className="w-full border-t border-slate-200/80 py-4 px-6 lg:px-8 text-center text-xs text-slate-500 font-sans flex flex-col sm:flex-row items-center justify-between gap-2 max-w-7xl mx-auto bg-white/50">
          <span>PlantPulse Manufacturing OS • Line 01 High-Precision Telemetry Bus</span>
          <div className="flex items-center gap-4 text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
              SCADA Bus: Operational
            </span>
            <span>•</span>
            <span>Latency: &lt;100ms</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
