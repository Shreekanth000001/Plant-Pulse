"use client";

import React from "react";
import { SetpointGauge } from "./SetpointGauge";

interface ReadingsGridProps {
  extra: Record<string, any>;
  subFacility?: string;
}

const UNIT_MAP: Record<string, { label: string; unit: string; std: number }> = {
  mold_temperature: { label: "Mold Temp", unit: "°C", std: 1.5 },
  extrusion_temperature: { label: "Extrusion Temp", unit: "°C", std: 1.5 },
  extrusion_speed: { label: "Extrusion Speed", unit: "mm/s", std: 1.0 },
  viscosity: { label: "Viscosity", unit: "cP", std: 2.0 },
  humidity: { label: "Humidity", unit: "%", std: 0.5 },
  torque: { label: "Torque", unit: "N·m", std: 3.0 },
  seal_pressure: { label: "Seal Pressure", unit: "bar", std: 0.4 },
};

function formatParamName(key: string): string {
  if (UNIT_MAP[key]) return UNIT_MAP[key].label;
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function getParamUnit(key: string): string {
  if (UNIT_MAP[key]) return UNIT_MAP[key].unit;
  if (key.includes("temp")) return "°C";
  if (key.includes("speed")) return "mm/s";
  if (key.includes("pressure")) return "bar";
  if (key.includes("torque")) return "N·m";
  if (key.includes("vibration")) return "mm/s";
  if (key.includes("percent") || key.includes("humidity")) return "%";
  return "";
}

function getParamStd(key: string): number {
  if (UNIT_MAP[key]) return UNIT_MAP[key].std;
  return 1.5;
}

export function ReadingsGrid({ extra, subFacility }: ReadingsGridProps) {
  if (!extra || Object.keys(extra).length === 0) {
    return (
      <div className="py-2 text-center text-xs text-slate-500 italic font-mono">
        No active process readings
      </div>
    );
  }

  // 1. Identify setpoint vs actual pairs
  const pairs: Array<{
    key: string;
    label: string;
    actual: number;
    setpoint: number;
    unit: string;
    std: number;
  }> = [];

  const pairedKeys = new Set<string>();

  for (const [key, value] of Object.entries(extra)) {
    if (key.endsWith("_setpoint")) {
      const baseKey = key.slice(0, -9);
      const actualKey = `${baseKey}_actual`;
      if (actualKey in extra && typeof extra[actualKey] === "number") {
        pairedKeys.add(key);
        pairedKeys.add(actualKey);
        pairs.push({
          key: baseKey,
          label: formatParamName(baseKey),
          actual: extra[actualKey],
          setpoint: Number(value),
          unit: getParamUnit(baseKey),
          std: getParamStd(baseKey),
        });
      }
    }
  }

  // 2. Identify remaining non-paired fields
  const standalone = Object.entries(extra).filter(
    ([k]) => !pairedKeys.has(k) && k !== "last_result" && k !== "stage_event"
  );

  return (
    <div className="flex flex-col gap-2">
      {/* Paired Setpoint vs Actual Readings */}
      {pairs.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
          {pairs.map((p) => (
            <SetpointGauge
              key={p.key}
              label={p.label}
              actual={p.actual}
              setpoint={p.setpoint}
              unit={p.unit}
              normalStd={p.std}
            />
          ))}
        </div>
      )}

      {/* Standalone fields (e.g. QC counts or standalone snapshot values) */}
      {standalone.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 pt-0.5">
          {standalone.map(([key, val]) => {
            const formattedLabel = formatParamName(key);
            const isNumber = typeof val === "number";
            const isPass = key.includes("pass") || key.includes("good");
            const isFail = key.includes("fail") || key.includes("reject");

            let valColor = "text-slate-200";
            if (isPass) valColor = "text-emerald-400";
            if (isFail) valColor = val > 0 ? "text-rose-400" : "text-slate-400";

            return (
              <div
                key={key}
                className="bg-slate-900/60 border border-slate-800/80 rounded p-1.5 flex flex-col justify-between"
              >
                <span className="text-[10px] text-slate-500 uppercase tracking-wider truncate">
                  {formattedLabel}
                </span>
                <span
                  className={`font-mono text-xs font-semibold tracking-tight ${valColor}`}
                >
                  {isNumber ? (val % 1 !== 0 ? val.toFixed(2) : val) : String(val)}
                  {isNumber && !key.includes("count") ? getParamUnit(key) : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
