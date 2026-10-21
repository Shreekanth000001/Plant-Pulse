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

/**
 * Safe sessionStorage wrappers with try/catch to protect against SSR or quota errors.
 */
export function safeSessionStorageGet<T>(
  key: string,
  fallback: T,
  storage?: Storage
): T {
  try {
    const store =
      storage ?? (typeof window !== "undefined" ? window.sessionStorage : undefined);
    if (!store) return fallback;
    const item = store.getItem(key);
    if (item === null) return fallback;
    return item as unknown as T;
  } catch {
    return fallback;
  }
}

export function safeSessionStorageSet(
  key: string,
  value: string,
  storage?: Storage
): void {
  try {
    const store =
      storage ?? (typeof window !== "undefined" ? window.sessionStorage : undefined);
    if (!store) return;
    store.setItem(key, value);
  } catch {
    // Quota exceeded or private browsing security restrictions
  }
}

export function safeSessionStorageRemove(
  key: string,
  storage?: Storage
): void {
  try {
    const store =
      storage ?? (typeof window !== "undefined" ? window.sessionStorage : undefined);
    if (!store) return;
    store.removeItem(key);
  } catch {
    // Ignore errors
  }
}

/**
 * Parse QC result payload supporting both canonical multi-plant envelope
 * ({ payload: { unit_id, outcome, ... } }) and flat legacy payloads ({ unit_id, outcome, ... }).
 */
export function parseQcResultPayload(rawPayload: unknown): {
  unit_id: string;
  outcome: "pass" | "fail" | string;
  probability?: number;
  defect_type?: string | null;
  attributed_stage?: string | null;
} | null {
  if (!rawPayload || typeof rawPayload !== "object") return null;

  const obj = rawPayload as Record<string, unknown>;
  const inner =
    obj.payload && typeof obj.payload === "object"
      ? (obj.payload as Record<string, unknown>)
      : obj;

  const unitId = (inner.unit_id as string) || (obj.unit_id as string);
  const rawOutcome = (inner.outcome as string) || (obj.outcome as string);

  if (!unitId || !rawOutcome) return null;

  const outcome = String(rawOutcome).toLowerCase();
  const probability =
    typeof inner.probability === "number"
      ? inner.probability
      : typeof obj.probability === "number"
      ? obj.probability
      : undefined;

  const defectType =
    (inner.defect_type as string) || (obj.defect_type as string) || null;
  const attributedStage =
    (inner.attributed_stage as string) ||
    (obj.attributed_stage as string) ||
    null;

  return {
    unit_id: unitId,
    outcome,
    probability,
    defect_type: defectType,
    attributed_stage: attributedStage,
  };
}

/**
 * Format string to upper-case safely, handling null/undefined/non-strings.
 */
export function safeToUpperCase(val: unknown, fallback: string = ""): string {
  if (val === null || val === undefined) return fallback;
  return String(val).toUpperCase();
}

/**
 * Extract status, sub_status, and metrics from telemetry payload,
 * supporting canonical envelope ({ payload: { status, sub_status, metrics } })
 * with fallback to flat payload ({ status, sub_status, readings, ... }).
 */
export function parseTelemetryPayload(rawPayload: unknown): {
  status?: string;
  sub_status?: string;
  current_unit_id?: string | null;
  starved?: boolean;
  good_count?: number;
  reject_count?: number;
  readings: Record<string, unknown>;
  vibration?: number;
} {
  if (!rawPayload || typeof rawPayload !== "object") {
    return { readings: {} };
  }

  const outer = rawPayload as Record<string, unknown>;
  const inner =
    outer.payload && typeof outer.payload === "object"
      ? (outer.payload as Record<string, unknown>)
      : outer;

  const status =
    (inner.status as string) ||
    (inner.state as string) ||
    (outer.status as string) ||
    (outer.state as string) ||
    undefined;

  const sub_status =
    (inner.sub_status as string) !== undefined
      ? (inner.sub_status as string)
      : (inner.phase as string) !== undefined
      ? (inner.phase as string)
      : (outer.sub_status as string) !== undefined
      ? (outer.sub_status as string)
      : (outer.phase as string) !== undefined
      ? (outer.phase as string)
      : undefined;

  const current_unit_id =
    (inner.current_unit_id as string) !== undefined
      ? (inner.current_unit_id as string | null)
      : (inner.current_unit as string) !== undefined
      ? (inner.current_unit as string | null)
      : (outer.current_unit_id as string) !== undefined
      ? (outer.current_unit_id as string | null)
      : (outer.current_unit as string) !== undefined
      ? (outer.current_unit as string | null)
      : undefined;

  const starved =
    inner.starved !== undefined
      ? Boolean(inner.starved)
      : outer.starved !== undefined
      ? Boolean(outer.starved)
      : undefined;

  const good_count =
    typeof inner.good_count === "number"
      ? inner.good_count
      : typeof outer.good_count === "number"
      ? outer.good_count
      : undefined;

  const reject_count =
    typeof inner.reject_count === "number"
      ? inner.reject_count
      : typeof outer.reject_count === "number"
      ? outer.reject_count
      : undefined;

  const readingsObj =
    (inner.metrics as Record<string, unknown>) ||
    (outer.readings as Record<string, unknown>) ||
    (inner.readings as Record<string, unknown>) ||
    inner;

  const vib =
    typeof readingsObj.vibration_rms_mms === "number"
      ? readingsObj.vibration_rms_mms
      : typeof readingsObj.vibration === "number"
      ? readingsObj.vibration
      : typeof readingsObj.vibration_mms === "number"
      ? readingsObj.vibration_mms
      : typeof inner.vibration_mms === "number"
      ? inner.vibration_mms
      : typeof inner.vibration === "number"
      ? inner.vibration
      : typeof outer.vibration_mms === "number"
      ? outer.vibration_mms
      : typeof outer.vibration === "number"
      ? outer.vibration
      : undefined;

  return {
    status,
    sub_status,
    ...(current_unit_id !== undefined ? { current_unit_id } : {}),
    ...(starved !== undefined ? { starved } : {}),
    ...(good_count !== undefined ? { good_count } : {}),
    ...(reject_count !== undefined ? { reject_count } : {}),
    readings: readingsObj,
    vibration: vib,
  };
}

export interface LastUpdatedInfo {
  text: string;
  secondsAgo: number | null;
  isAmber: boolean;
}

/**
 * Computes last updated relative string and whether it has exceeded 10s amber threshold.
 */
export function formatLastUpdated(
  lastMessageAt: string | number | null | undefined,
  now: number = Date.now()
): LastUpdatedInfo {
  if (!lastMessageAt) {
    return {
      text: "No telemetry yet",
      secondsAgo: null,
      isAmber: false,
    };
  }

  const timestampMs =
    typeof lastMessageAt === "number"
      ? lastMessageAt
      : new Date(lastMessageAt).getTime();

  if (isNaN(timestampMs)) {
    return {
      text: "No telemetry yet",
      secondsAgo: null,
      isAmber: false,
    };
  }

  const secondsAgo = Math.max(0, Math.floor((now - timestampMs) / 1000));
  const isAmber = secondsAgo >= 10;

  return {
    text: `last updated ${secondsAgo}s ago`,
    secondsAgo,
    isAmber,
  };
}

export interface ConnectionModeInfo {
  mode: "live" | "polled" | "reconnecting" | "offline" | "token_required";
  label: string;
  isLive: boolean;
  isPolled: boolean;
}

/**
 * Returns user-facing connection state label stating whether data is live or polled.
 */
export function getConnectionModeLabel(
  status: string,
  pollingActive: boolean
): ConnectionModeInfo {
  if (status === "connected") {
    if (pollingActive) {
      return {
        mode: "polled",
        label: "Polled",
        isLive: false,
        isPolled: true,
      };
    }
    return {
      mode: "live",
      label: "Live (WebSocket)",
      isLive: true,
      isPolled: false,
    };
  }

  if (status === "token_required") {
    return {
      mode: "token_required",
      label: pollingActive ? "Polled (5s)" : "Token Required",
      isLive: false,
      isPolled: pollingActive,
    };
  }

  if (status === "reconnecting") {
    return {
      mode: "reconnecting",
      label: "Reconnecting",
      isLive: false,
      isPolled: false,
    };
  }

  return {
    mode: "offline",
    label: "Offline",
    isLive: false,
    isPolled: false,
  };
}

export interface HistoryQueryParamsOptions {
  rangePreset?: "1h" | "6h" | "12h" | "24h";
  start?: string | Date;
  end?: string | Date;
  points?: number;
  now?: Date;
}

export function buildHistoryQueryParams(options: HistoryQueryParamsOptions = {}): {
  start: string;
  end: string;
  points: number;
} {
  const points = Math.min(Math.max(options.points ?? 300, 10), 500);
  const now = options.now ?? new Date();

  let endDt: Date;
  if (options.end) {
    endDt = typeof options.end === "string" ? new Date(options.end) : options.end;
  } else {
    endDt = now;
  }

  let startDt: Date;
  if (options.start) {
    startDt = typeof options.start === "string" ? new Date(options.start) : options.start;
  } else {
    let hours = 1;
    if (options.rangePreset === "6h") hours = 6;
    else if (options.rangePreset === "12h") hours = 12;
    else if (options.rangePreset === "24h") hours = 24;
    startDt = new Date(endDt.getTime() - hours * 3600 * 1000);
  }

  const formatIso = (d: Date) => d.toISOString().replace(/\.000Z$/, "Z");

  return {
    start: formatIso(startDt),
    end: formatIso(endDt),
    points,
  };
}

export interface TimePointWithGaps {
  timestamp?: string;
  bucket_start?: string;
  avg: number | null;
  min?: number | null;
  max?: number | null;
  last?: number | null;
  count?: number | null;
}

export function insertTimeGaps<T extends TimePointWithGaps>(
  data: T[],
  bucketSeconds: number,
  maxGapFactor: number = 1.5
): T[] {
  if (!data || data.length <= 1) {
    return data ? [...data] : [];
  }

  const result: T[] = [];
  const thresholdMs = bucketSeconds * maxGapFactor * 1000;

  for (let i = 0; i < data.length; i++) {
    result.push(data[i]);
    if (i < data.length - 1) {
      const currStr = data[i].bucket_start || data[i].timestamp || "";
      const nextStr = data[i + 1].bucket_start || data[i + 1].timestamp || "";
      const currTime = new Date(currStr).getTime();
      const nextTime = new Date(nextStr).getTime();
      if (!isNaN(currTime) && !isNaN(nextTime) && nextTime - currTime > thresholdMs) {
        const gapTime = new Date(currTime + bucketSeconds * 1000).toISOString();
        const gapPoint: T = {
          ...data[i],
          avg: null,
          min: null,
          max: null,
          last: null,
          count: 0,
        };
        const rec = gapPoint as unknown as Record<string, unknown>;
        if (data[i].bucket_start !== undefined) {
          rec.bucket_start = gapTime;
        }
        if (data[i].timestamp !== undefined) {
          rec.timestamp = gapTime;
        }
        result.push(gapPoint);
      }
    }
  }

  return result;
}

export interface DemoHint {
  plantId: string;
  token: string;
  message: string;
}

/**
 * Returns demo access token hint for evaluating the water booster pump demo
 * strictly when DEMO_HINTS is enabled.
 */
export function getDemoHintForPlant(
  plantId: string,
  demoHintsEnabled?: boolean | string
): DemoHint | null {
  const isEnabled =
    demoHintsEnabled === true ||
    demoHintsEnabled === "true" ||
    demoHintsEnabled === "1";

  if (!isEnabled) {
    return null;
  }

  if (plantId === "plant_water_district_9") {
    return {
      plantId,
      token: "district9_read_secret_token_889",
      message:
        "Demo Token: district9_read_secret_token_889 (configured via .env for evaluation)",
    };
  }

  return null;
}
