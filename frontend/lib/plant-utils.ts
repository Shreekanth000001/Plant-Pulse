import type {
  PublicPlantDefinition,
  PlantMachineLatest,
  PlantMachineSignalValue,
} from "../types/factory";

/**
 * Banner "line is filling" depends on data only:
 * quality_inspection enabled and zero QC results.
 * No plant IDs or hardcoded plant names in UI logic.
 */
export function shouldShowLineIsFillingBanner(args: {
  enabledModules?: string[];
  qcResultCount: number;
}): boolean {
  const hasQualityModule = Boolean(args.enabledModules?.includes("quality_inspection"));
  return hasQualityModule && args.qcResultCount === 0;
}

/**
 * Handle plants or machines with no telemetry yet:
 * show "no data yet" for missing/null/NaN readings, never blank or NaN.
 */
export function formatSignalReading(val: unknown, unit?: string): string {
  if (val === undefined || val === null || val === "") {
    return "no data yet";
  }
  if (typeof val === "number") {
    if (Number.isNaN(val)) return "no data yet";
    const formatted = val.toFixed(2);
    return unit ? `${formatted} ${unit}` : formatted;
  }
  return String(val);
}

/**
 * Module gating: check if a specific module is present in enabled_modules.
 */
export function isModuleEnabled(
  enabledModules: string[] | undefined,
  moduleName: string
): boolean {
  return Boolean(enabledModules && enabledModules.includes(moduleName));
}

export interface OverviewSignalView {
  signal_code: string;
  name: string;
  unit: string;
  data_type: string;
  is_setpoint?: boolean;
  setpoint_signal_code?: string | null;
  normal_min?: number | null;
  normal_max?: number | null;
  warn_min?: number | null;
  warn_max?: number | null;
  alarm_min?: number | null;
  alarm_max?: number | null;
  display_order: number;
  rawValue?: number | string | boolean | null;
  formattedValue: string;
  device_timestamp?: string | null;
}

export interface OverviewMachineView {
  machine_code: string;
  area_code: string;
  name: string;
  machine_type?: string | null;
  display_order: number;
  state: string;
  sub_state?: string | null;
  last_seen_at?: string | null;
  signals: OverviewSignalView[];
}

export interface OverviewAreaView {
  area_code: string;
  name: string;
  display_order: number;
  machines: OverviewMachineView[];
}

/**
 * Build dynamic areas and machines hierarchy from PlantDefinition and latest machine states.
 * Fully sorted by display_order to ensure stable layouts and prevent layout shifts.
 */
export function buildAreaOverview(
  definition: PublicPlantDefinition | null,
  machinesLatest: PlantMachineLatest[] = []
): OverviewAreaView[] {
  if (!definition || !definition.areas) return [];

  const latestMap = new Map<string, PlantMachineLatest>();
  for (const m of machinesLatest) {
    latestMap.set(m.machine_code, m);
  }

  const sortedAreas = [...definition.areas].sort(
    (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)
  );

  return sortedAreas.map((area) => {
    const sortedMachines = [...(area.machines || [])].sort(
      (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)
    );

    const machineViews: OverviewMachineView[] = sortedMachines.map((mDef) => {
      const latest = latestMap.get(mDef.machine_code);
      const state = latest?.state || "OFFLINE";
      const subState = latest?.sub_state ?? null;
      const lastSeenAt = latest?.last_seen_at ?? null;

      const sortedSignals = [...(mDef.signals || [])].sort(
        (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)
      );

      const signals: OverviewSignalView[] = sortedSignals.map((sDef) => {
        const sigData: PlantMachineSignalValue | undefined =
          latest?.signals?.[sDef.signal_code];
        const rawValue = sigData?.value ?? null;
        const formattedValue = formatSignalReading(rawValue, sDef.unit);

        return {
          signal_code: sDef.signal_code,
          name: sDef.name,
          unit: sDef.unit,
          data_type: sDef.data_type,
          is_setpoint: sDef.is_setpoint,
          setpoint_signal_code: sDef.setpoint_signal_code,
          normal_min: sDef.normal_min,
          normal_max: sDef.normal_max,
          warn_min: sDef.warn_min,
          warn_max: sDef.warn_max,
          alarm_min: sDef.alarm_min,
          alarm_max: sDef.alarm_max,
          display_order: sDef.display_order ?? 0,
          rawValue,
          formattedValue,
          device_timestamp: sigData?.device_timestamp ?? null,
        };
      });

      return {
        machine_code: mDef.machine_code,
        area_code: area.area_code,
        name: mDef.name,
        machine_type: mDef.machine_type,
        display_order: mDef.display_order ?? 0,
        state,
        sub_state: subState,
        last_seen_at: lastSeenAt,
        signals,
      };
    });

    return {
      area_code: area.area_code,
      name: area.name,
      display_order: area.display_order ?? 0,
      machines: machineViews,
    };
  });
}

export interface WsCloseHandlingResult {
  status: "token_required" | "reconnecting" | "disconnected";
  shouldReconnect: boolean;
  isTokenRequired: boolean;
  fallbackPollingIntervalMs: number | null;
}

/**
 * WebSocket close code handling:
 * Code 4401 transitions directly to token_required and begins 5s polling fallback.
 */
export function handleWsCloseState(code: number): WsCloseHandlingResult {
  if (code === 4401) {
    return {
      status: "token_required",
      shouldReconnect: false,
      isTokenRequired: true,
      fallbackPollingIntervalMs: 5000,
    };
  }
  return {
    status: "reconnecting",
    shouldReconnect: true,
    isTokenRequired: false,
    fallbackPollingIntervalMs: null,
  };
}

/**
 * Safe localStorage wrapper with try/catch to protect against SSR or quota errors.
 */
export function safeLocalStorageGet<T>(
  key: string,
  fallback: T,
  storage?: Storage
): T {
  try {
    const store =
      storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
    if (!store) return fallback;
    const item = store.getItem(key);
    if (item === null) return fallback;
    return item as unknown as T;
  } catch {
    return fallback;
  }
}

export function safeLocalStorageSet(
  key: string,
  value: string,
  storage?: Storage
): void {
  try {
    const store =
      storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
    if (!store) return;
    store.setItem(key, value);
  } catch {
    // Quota exceeded or private browsing security restrictions
  }
}
