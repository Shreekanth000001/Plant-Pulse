import React from "react";
import { SetpointGauge } from "./SetpointGauge";
import type { Readings, SignalDefinition } from "../../types/factory";
import { formatSignalReading } from "../../lib/plant-utils";

interface ReadingsGridProps {
  extra: Readings;
  subFacility?: string;
  signalDefinitions?: SignalDefinition[];
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
  if (!key) return "";
  if (UNIT_MAP[key]) return UNIT_MAP[key].label;
  return String(key)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => (char ? char.toUpperCase() : ""));
}

function getParamUnit(key: string): string {
  if (!key) return "";
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

export function ReadingsGrid({ extra, signalDefinitions }: ReadingsGridProps) {
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

  if (extra) {
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
            actual: extra[actualKey] as number,
            setpoint: Number(value),
            unit: getParamUnit(baseKey),
            std: getParamStd(baseKey),
          });
        }
      }
    }
  }

  // 2. Identify standalone items (from signalDefinitions first, then extra)
  type StandaloneItem = {
    key: string;
    label: string;
    value: unknown;
    unit?: string;
  };

  const standalone: StandaloneItem[] = [];
  const handledKeys = new Set<string>(pairedKeys);
  handledKeys.add("last_result");
  handledKeys.add("stage_event");

  if (signalDefinitions && signalDefinitions.length > 0) {
    const sortedDefs = [...signalDefinitions].sort(
      (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)
    );
    for (const sig of sortedDefs) {
      if (pairedKeys.has(sig.signal_code) || pairedKeys.has(`${sig.signal_code}_actual`)) {
        continue;
      }
      handledKeys.add(sig.signal_code);
      const val = extra ? extra[sig.signal_code] : undefined;
      standalone.push({
        key: sig.signal_code,
        label: sig.name || formatParamName(sig.signal_code),
        value: val,
        unit: sig.unit,
      });
    }
  }

  // Also include any leftover keys in extra that were not defined in signalDefinitions
  if (extra) {
    for (const [k, val] of Object.entries(extra)) {
      if (!handledKeys.has(k)) {
        standalone.push({
          key: k,
          label: formatParamName(k),
          value: val,
          unit: k.includes("count") ? undefined : getParamUnit(k),
        });
      }
    }
  }

  if (pairs.length === 0 && standalone.length === 0) {
    return (
      <div className="py-2 text-center text-xs text-slate-400 italic font-mono">
        No active process readings
      </div>
    );
  }

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

      {/* Standalone fields (e.g. QC counts, defined signals, or snapshot values) */}
      {standalone.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 pt-0.5">
          {standalone.map((item) => {
            const formattedLabel = item.label;
            const formattedVal = formatSignalReading(item.value, item.unit);
            const isNoData = formattedVal === "no data yet";

            const isPass = item.key.includes("pass") || item.key.includes("good");
            const isFail = item.key.includes("fail") || item.key.includes("reject");

            let valColor = "text-slate-900";
            if (isNoData) {
              valColor = "text-slate-400 italic font-sans font-normal";
            } else if (isPass) {
              valColor = "text-emerald-700 font-bold";
            } else if (isFail) {
              valColor = typeof item.value === "number" && item.value > 0 ? "text-rose-600 font-bold" : "text-slate-500";
            }

            return (
              <div
                key={item.key}
                className="bg-slate-50 border border-slate-200/80 rounded-lg p-1.5 flex flex-col justify-between shadow-2xs"
              >
                <span className="text-[10px] text-slate-500 uppercase tracking-wider truncate font-semibold" title={formattedLabel}>
                  {formattedLabel}
                </span>
                <span
                  className={`font-mono tabular-nums text-xs font-bold tracking-tight ${valColor}`}
                >
                  {formattedVal}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
