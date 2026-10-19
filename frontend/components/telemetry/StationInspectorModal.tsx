import React, { useEffect, useRef } from "react";
import Link from "next/link";
import type { MachineStatus, MachineDefinition } from "../../types/factory";
import { ReadingsGrid } from "./ReadingsGrid";

interface StationInspectorModalProps {
  machineId: string | null;
  machine: MachineStatus | null;
  machineDef?: MachineDefinition;
  onClose: () => void;
}

export function StationInspectorModal({
  machineId,
  machine,
  machineDef,
  onClose,
}: StationInspectorModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previousActiveElement = document.activeElement as HTMLElement | null;

    // Focus the first focusable element inside the modal on open
    const focusable = modalRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable && focusable.length > 0) {
      focusable[0].focus();
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }

      // Trap Tab key within modal
      if (e.key === "Tab" && modalRef.current) {
        const focusables = Array.from(
          modalRef.current.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          )
        ).filter((el) => !el.hasAttribute("disabled") && el.offsetParent !== null);

        if (focusables.length === 0) return;

        const first = focusables[0];
        const last = focusables[focusables.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousActiveElement?.focus();
    };
  }, [onClose]);

  if (!machineId || !machine) return null;

  const displayName = machine.name || machineId;
  const state = machine.machine_state?.toUpperCase() || "OFFLINE";
  const isStarved = machine.starved;

  let stateColor = "text-slate-600 bg-slate-100 border-slate-200";
  if (state === "FAULT") {
    stateColor = "text-rose-700 bg-rose-50 border-rose-200";
  } else if (state === "RUNNING") {
    stateColor = "text-emerald-700 bg-emerald-50 border-emerald-200";
  } else if (state === "IDLE" || isStarved) {
    stateColor = "text-amber-800 bg-amber-50 border-amber-200";
  }

  const vibration = machine.vibration ?? null;
  const vibrationFaultThreshold = 7.0;
  const isVibrationFault = vibration !== null && vibration >= vibrationFaultThreshold;
  const isVibrationHigh = vibration !== null && vibration > 4.5;

  const good = machine.good_count ?? 0;
  const reject = machine.reject_count ?? 0;
  const total = good + reject;
  const scrapRate = total > 0 ? ((reject / total) * 100).toFixed(1) : "0.0";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs animate-fadeIn"
      onClick={onClose}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="station-inspector-title"
        className="bg-white rounded-3xl w-full max-w-2xl border border-slate-200 shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Top Bar */}
        <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/80">
          <div className="flex items-center gap-3.5">
            <div className="w-11 h-11 rounded-2xl bg-blue-100/70 border border-blue-200 flex items-center justify-center text-blue-700 font-mono font-bold text-sm shadow-xs">
              {(machineId || "").toUpperCase()}
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h3
                  id="station-inspector-title"
                  className="text-lg font-bold text-slate-900 tracking-tight"
                >
                  {displayName}
                </h3>
                <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border capitalize ${stateColor}`}>
                  {isStarved ? "Starved" : state.toLowerCase()}
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5 capitalize">
                Sub-facility: {machine.sub_facility} Station • Live Telemetry Stream
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            aria-label="Close station inspector"
            className="w-9 h-9 rounded-xl bg-white hover:bg-slate-100 text-slate-500 hover:text-slate-800 border border-slate-200 flex items-center justify-center transition-all cursor-pointer shadow-2xs"
          >
            ✕
          </button>
        </div>

        {/* Modal Scrollable Body */}
        <div className="p-6 overflow-y-auto flex flex-col gap-6">
          {/* Active Unit Banner */}
          <div className="bg-slate-50/70 rounded-2xl p-4 flex items-center justify-between border border-slate-200">
            <div>
              <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                Currently Processing Unit
              </div>
              {machine.current_unit_id ? (
                <div className="flex items-center gap-2 mt-1">
                  <span className="font-mono text-sm font-bold text-blue-600">
                    {machine.current_unit_id}
                  </span>
                  {machine.phase && (
                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-white text-slate-700 border border-slate-200">
                      Phase: {machine.phase}
                    </span>
                  )}
                </div>
              ) : (
                <div className="text-xs text-slate-400 italic mt-1 font-sans">
                  Station currently waiting for incoming buffer unit.
                </div>
              )}
            </div>

            {machine.current_unit_id && (
              <Link
                href={`/units/${encodeURIComponent(machine.current_unit_id)}`}
                className="px-3.5 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold shadow-xs transition-all flex items-center gap-1.5"
              >
                <span>Trace Unit Journey</span>
                <span>→</span>
              </Link>
            )}
          </div>

          {/* Mechanical Diagnostics & Vibration Wear */}
          <div className="bg-slate-50/70 rounded-2xl p-5 flex flex-col gap-3 border border-slate-200">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 tracking-tight flex items-center gap-2">
                <span>Mechanical Bearing & Motor Vibration</span>
                <span className="text-[10px] text-slate-500 font-normal">
                  (Safety limit: 7.0 mm/s)
                </span>
              </span>
              <span
                className={`font-mono text-xs font-bold ${
                  isVibrationFault
                    ? "text-rose-600"
                    : isVibrationHigh
                    ? "text-amber-700"
                    : "text-emerald-700"
                }`}
              >
                {vibration !== null ? `${vibration.toFixed(2)} mm/s` : "Normal"}
              </span>
            </div>

            {/* Vibration progress gauge */}
            <div className="w-full bg-slate-200 rounded-full h-2.5 overflow-hidden border border-slate-100">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  isVibrationFault
                    ? "bg-rose-500"
                    : isVibrationHigh
                    ? "bg-amber-400"
                    : "bg-emerald-500"
                }`}
                style={{
                  width: `${Math.min(
                    100,
                    vibration !== null ? (vibration / vibrationFaultThreshold) * 100 : 25
                  )}%`,
                }}
              />
            </div>

            <div className="flex items-center justify-between text-[11px] text-slate-500">
              <span>Baseline: 1.5 - 2.5 mm/s</span>
              <span>Degradation: {machine.vibration_wear_level ? `${(machine.vibration_wear_level * 100).toFixed(0)}%` : "Nominal"}</span>
            </div>
          </div>

          {/* Process Telemetry Parameters */}
          <div className="flex flex-col gap-2.5">
            <div className="text-xs font-bold text-slate-900 tracking-tight">
              Streaming Process Sensor Readings & Setpoints
            </div>
            <ReadingsGrid
              extra={machine.extra || {}}
              subFacility={machine.sub_facility}
              signalDefinitions={machineDef?.signals}
            />
          </div>

          {/* Shift Production Counters */}
          <div className="grid grid-cols-3 gap-3 pt-2">
            <div className="bg-slate-50 border border-slate-200 rounded-2xl p-3.5 flex flex-col justify-between">
              <span className="text-[11px] font-semibold text-slate-500">Total Produced</span>
              <span className="text-xl font-bold font-mono text-slate-900 mt-1">
                {total}
              </span>
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-2xl p-3.5 flex flex-col justify-between">
              <span className="text-[11px] font-semibold text-slate-500">Good Units</span>
              <span className="text-xl font-bold font-mono text-emerald-700 mt-1">
                {good}
              </span>
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-2xl p-3.5 flex flex-col justify-between">
              <span className="text-[11px] font-semibold text-slate-500">Scrap Rate</span>
              <span className={`text-xl font-bold font-mono mt-1 ${Number(scrapRate) > 5 ? "text-amber-800" : "text-slate-700"}`}>
                {scrapRate}%
              </span>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="p-4 border-t border-slate-100 bg-slate-50/80 flex items-center justify-between text-xs text-slate-500">
          <span>Tick: {machine.timestamp ? new Date(machine.timestamp).toLocaleTimeString() : "Live stream"}</span>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-medium transition-colors cursor-pointer shadow-xs"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
