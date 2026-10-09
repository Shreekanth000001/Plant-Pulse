import {
  MachineStatus,
  UnitHistoryResponse,
  DefectRateByHour,
  DefectRateByStage,
} from "../types/factory";

/**
 * Returns the sanitized base URL for API requests.
 * Strips whitespace and trailing slashes.
 */
export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl) {
    return envUrl.trim().replace(/\/+$/, "");
  }
  return "http://localhost:8000";
}

/**
 * Returns the sanitized WebSocket URL.
 */
export function getWsUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_WS_URL;
  if (envUrl) {
    return envUrl.trim();
  }
  return "ws://localhost:8000/ws/telemetry";
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Fetch latest telemetry for all machines.
 */
export async function fetchLatestMachines(): Promise<MachineStatus[]> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/machines/latest`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch machines: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch full history and QC result for a given unit.
 */
export async function fetchUnitHistory(
  unitId: string
): Promise<UnitHistoryResponse> {
  const baseUrl = getApiBaseUrl();
  const cleanId = encodeURIComponent(unitId.trim());
  const res = await fetch(`${baseUrl}/api/units/${cleanId}`, {
    cache: "no-store",
  });

  if (res.status === 404) {
    throw new ApiError(`Unit '${unitId}' not found in registry`, 404);
  }

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch unit ${unitId}: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch defect rate by hour of the day.
 */
export async function fetchDefectRateByHour(): Promise<DefectRateByHour[]> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/stats/defect-rate-by-hour`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch hourly defect rate: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch defect rate grouped by attributed stage.
 */
export async function fetchDefectRateByStage(): Promise<DefectRateByStage[]> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/stats/defect-rate-by-stage`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch stage defect rate: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}
