"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { useFactoryWebSocket } from "../../context/WebSocketContext";
import { isModuleEnabled } from "../../lib/plant-utils";

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

interface NavLinkItem {
  label: string;
  href: string;
  icon: React.ReactNode;
  badge?: string;
  badgeColor?: string;
}

interface NavGroup {
  group: string;
  links: NavLinkItem[];
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const { status, machines, plantDefinition, selectedPlantId } =
    useFactoryWebSocket();
  const { isSignedIn, user } = useUser();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const machineList = Object.values(machines);
  const runningCount = machineList.filter(
    (m) => m.machine_state === "RUNNING" || m.machine_state === "TESTING"
  ).length;
  const faultCount = machineList.filter(
    (m) => m.machine_state === "FAULT"
  ).length;

  const isNavActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  const hasTraceability = isModuleEnabled(
    plantDefinition?.enabled_modules,
    "product_traceability"
  );
  const hasQuality = isModuleEnabled(
    plantDefinition?.enabled_modules,
    "quality_inspection"
  );

  const navItems: NavGroup[] = [
    {
      group: "OPERATIONS",
      links: [
        {
          label: "Live Floor Overview",
          href: "/",
          badge: `${runningCount}/${machineList.length || 0}`,
          badgeColor: "bg-emerald-50 text-emerald-700 border-emerald-200",
          icon: (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
            </svg>
          ),
        },
      ],
    },
  ];

  const qualityLinks: NavLinkItem[] = [];
  if (hasTraceability) {
    qualityLinks.push({
      label: "Unit Traceability",
      href: "/units",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
        </svg>
      ),
    });
  }
  if (hasQuality) {
    qualityLinks.push({
      label: "Quality Analytics",
      href: "/analytics",
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      ),
    });
  }

  if (qualityLinks.length > 0) {
    navItems.push({
      group: "QUALITY & GENEALOGY",
      links: qualityLinks,
    });
  }

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 z-40 bg-slate-900/30 backdrop-blur-xs lg:hidden"
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 w-64 bg-white border-r border-slate-200/90 flex flex-col justify-between transition-transform duration-300 shadow-xs lg:translate-x-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Top: Brand & Plant Info Card */}
        <div className="flex flex-col gap-5 p-5 border-b border-slate-100">
          <Link href="/" className="flex items-center gap-3 group">
            <div className="w-9 h-9 rounded-xl bg-blue-600 text-white flex items-center justify-center shadow-xs shadow-blue-500/25 group-hover:bg-blue-700 transition-colors">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-900 tracking-tight text-base group-hover:text-blue-600 transition-colors">
                  PlantPulse
                </span>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                  OS 2.0
                </span>
              </div>
              <div className="text-[11px] text-slate-500">
                Plant Telemetry & Operations
              </div>
            </div>
          </Link>

          {/* Dynamic Facility Card */}
          <div className="bg-slate-50 rounded-xl p-2.5 flex items-center justify-between border border-slate-200">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-7 h-7 rounded-lg bg-blue-100/70 border border-blue-200/60 flex items-center justify-center text-blue-700 text-xs shrink-0">
                🏭
              </div>
              <div className="min-w-0">
                <div className="text-xs font-semibold text-slate-800 truncate">
                  {plantDefinition?.name || selectedPlantId}
                </div>
                <div className="text-[10px] text-slate-500 font-mono truncate">
                  {plantDefinition?.timezone || "UTC"} • {plantDefinition?.areas?.length || 0} Areas
                </div>
              </div>
            </div>
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                status === "connected"
                  ? "bg-emerald-500 animate-pulse"
                  : status === "token_required"
                  ? "bg-blue-500 animate-pulse"
                  : "bg-amber-400"
              }`}
              title={`Status: ${status}`}
            />
          </div>
        </div>

        {/* Center: Dynamic Navigation Menu */}
        <div className="flex-1 overflow-y-auto px-3.5 py-5 flex flex-col gap-6">
          {navItems.map((group) => (
            <div key={group.group} className="flex flex-col gap-1.5">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 px-3">
                {group.group}
              </div>
              {group.links.map((link) => {
                const active = isNavActive(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    onClick={onClose}
                    className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-medium transition-all duration-150 ${
                      active
                        ? "bg-blue-50 text-blue-700 border border-blue-200 font-semibold shadow-xs"
                        : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span className={active ? "text-blue-600" : "text-slate-400"}>
                        {link.icon}
                      </span>
                      <span>{link.label}</span>
                    </div>

                    {link.badge && (
                      <span
                        className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${link.badgeColor}`}
                      >
                        {link.badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}

          {/* Quick Line Health Stats Widget */}
          <div className="bg-slate-50 rounded-2xl p-3.5 flex flex-col gap-2.5 mt-auto border border-slate-200">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500 font-medium">Plant Status</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200 font-semibold uppercase">
                {status === "token_required" ? "SNAPSHOT 5S" : status}
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px] text-slate-600">
              <span>Operational:</span>
              <strong className="text-slate-900 font-mono font-semibold">
                {runningCount} Stations
              </strong>
            </div>
            <div className="flex items-center justify-between text-[11px] text-slate-600">
              <span>Active Faults:</span>
              <strong
                className={
                  faultCount > 0
                    ? "text-rose-600 font-mono font-bold"
                    : "text-emerald-600 font-mono font-semibold"
                }
              >
                {faultCount}
              </strong>
            </div>
          </div>
        </div>

        {/* Bottom: Operator Shift Profile */}
        <div className="p-4 border-t border-slate-200 bg-slate-50/70 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            {mounted && isSignedIn && user?.imageUrl ? (
              <img
                src={user.imageUrl}
                alt={user.fullName || "User avatar"}
                className="w-8 h-8 rounded-full object-cover shadow-xs border border-slate-200 shrink-0"
              />
            ) : (
              <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-xs font-bold text-white shadow-xs shrink-0">
                {mounted && isSignedIn && user?.firstName
                  ? `${user.firstName[0]}${user.lastName ? user.lastName[0] : ""}`.toUpperCase()
                  : "OP"}
              </div>
            )}
            <div className="min-w-0">
              <div className="text-xs font-semibold text-slate-900 truncate max-w-[130px]">
                {mounted && isSignedIn && user
                  ? user.fullName ||
                    user.firstName ||
                    user.primaryEmailAddress?.emailAddress?.split("@")[0] ||
                    "Operator"
                  : "Plant Operator"}
              </div>
              <div className="text-[10px] text-slate-500 truncate max-w-[130px]">
                Plant: {plantDefinition?.timezone || "UTC"}
              </div>
            </div>
          </div>
          <div className="w-2 h-2 rounded-full bg-emerald-500 ring-4 ring-emerald-100 shrink-0" />
        </div>
      </aside>
    </>
  );
}
