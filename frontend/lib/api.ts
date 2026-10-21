import type {
  MachineStatus,
  UnitHistoryResponse,
  RecentUnitItem,
  DefectRateByHour,
  DefectRateByStage,
  BackendQueueDepths,
  PlantSummary,
  PublicPlantDefinition,
  PlantMachineLatest,
  SignalHistoryResponse,
} from "../types/factory";

export function getErrorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * Returns the sanitized base URL for API requests.
 * Strips whitespace and trailing slashes.
 */
export function getApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl) {
    return envUrl.trim().replace(/\/+$/, "");
  }
  if (typeof window !== "undefined" && window.location) {
    const hostname = window.location.hostname || "localhost";
    const protocol = window.location.protocol === "https:" ? "https:" : "http:";
    return `${protocol}//${hostname}:8000`;
  }
  return "http://localhost:8000";
}

/**
 * Returns the sanitized WebSocket URL for a given plant or the legacy stream.
 * If NEXT_PUBLIC_WS_URL is unset, derives host from window.location at runtime
 * (same hostname, port 8000, ws or wss matching the page protocol).
 * Optionally appends single-use ws-ticket query param if provided.
 */
export function getWsUrl(plantId?: string, ticket?: string | null): string {
  const envWs = process.env.NEXT_PUBLIC_WS_URL;
  let baseWs = "ws://localhost:8000";
  if (envWs) {
    baseWs = envWs.trim().replace(/\/+$/, "");
    // If NEXT_PUBLIC_WS_URL includes a path like /ws/telemetry, extract host origin
    if (baseWs.includes("/ws/")) {
      baseWs = baseWs.split("/ws/")[0].replace(/\/+$/, "");
    }
  } else if (typeof window !== "undefined" && window.location) {
    const hostname = window.location.hostname || "localhost";
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    baseWs = `${wsProtocol}//${hostname}:8000`;
  }

  if (plantId) {
    let url = `${baseWs}/ws/${encodeURIComponent(plantId.trim())}/telemetry`;
    if (ticket) {
      url += `?ticket=${encodeURIComponent(ticket.trim())}`;
    }
    return url;
  }
  return `${baseWs}/ws/telemetry`;
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
 * Fetch all registered plants.
 */
export async function fetchPlants(): Promise<PlantSummary[]> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/plants`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch plants: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Request a single-use WebSocket ticket for a plant using the viewer token.
 */
export async function createWsTicket(
  plantId: string,
  token?: string | null
): Promise<{ ticket: string; expires_in: number }> {
  const baseUrl = getApiBaseUrl();
  const cleanId = encodeURIComponent(plantId.trim());
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token.trim()}`;
  }

  const res = await fetch(`${baseUrl}/api/plants/${cleanId}/ws-ticket`, {
    method: "POST",
    headers,
    cache: "no-store",
    body: JSON.stringify({}),
  });

  if (res.status === 401) {
    throw new ApiError("Unauthorized", 401);
  }

  if (res.status === 404) {
    throw new ApiError(`Plant '${plantId}' not found`, 404);
  }

  if (!res.ok) {
    throw new ApiError(
      `Failed to issue WS ticket for plant '${plantId}': ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch public plant definition (omits passwords and viewer tokens).
 */
export async function fetchPlantDefinition(
  plantId: string,
  token?: string | null
): Promise<PublicPlantDefinition> {
  const baseUrl = getApiBaseUrl();
  const cleanId = encodeURIComponent(plantId.trim());
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token.trim()}`;
  }

  const res = await fetch(`${baseUrl}/api/plants/${cleanId}/definition`, {
    cache: "no-store",
    headers,
  });

  if (res.status === 401) {
    throw new ApiError("Unauthorized", 401);
  }

  if (res.status === 404) {
    throw new ApiError(`Plant '${plantId}' not found`, 404);
  }

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch definition for plant '${plantId}': ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch latest telemetry and states for all machines of a plant.
 */
export async function fetchPlantMachinesLatest(
  plantId: string,
  token?: string | null
): Promise<PlantMachineLatest[]> {
  const baseUrl = getApiBaseUrl();
  const cleanId = encodeURIComponent(plantId.trim());
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token.trim()}`;
  }

  const res = await fetch(`${baseUrl}/api/plants/${cleanId}/machines/latest`, {
    cache: "no-store",
    headers,
  });

  if (res.status === 401) {
    throw new ApiError("Unauthorized", 401);
  }

  if (res.status === 404) {
    throw new ApiError(`Plant '${plantId}' not found`, 404);
  }

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch latest machines for plant '${plantId}': ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch latest telemetry for all machines (legacy endpoint).
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
 * Fetch full history and QC result for a given unit within a plant.
 */
export async function fetchUnitHistory(
  plantId: string,
  unitId: string,
  token?: string | null
): Promise<UnitHistoryResponse> {
  const baseUrl = getApiBaseUrl();
  const cleanPlantId = encodeURIComponent(plantId.trim());
  const cleanId = encodeURIComponent(unitId.trim());
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token.trim()}`;
  }
  const res = await fetch(`${baseUrl}/api/plants/${cleanPlantId}/units/${cleanId}`, {
    cache: "no-store",
    headers,
  });

  if (res.status === 401) {
    throw new ApiError("Unauthorized", 401);
  }

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

/**
 * Fetch current queue sizes between production stages for a plant.
 */
export async function fetchPlantQueueDepths(
  plantId: string,
  token?: string | null
): Promise<BackendQueueDepths> {
  const baseUrl = getApiBaseUrl();
  const cleanId = encodeURIComponent(plantId.trim());
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token.trim()}`;
  }

  const res = await fetch(`${baseUrl}/api/plants/${cleanId}/queue-depths`, {
    cache: "no-store",
    headers,
  });

  if (res.status === 401) {
    throw new ApiError("Unauthorized", 401);
  }

  if (res.status === 404) {
    throw new ApiError(`Queue depths not available for plant '${plantId}'`, 404);
  }

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch queue depths for plant '${plantId}': ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch current queue sizes between production stages.
 */
export async function fetchQueueDepths(): Promise<BackendQueueDepths> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/queue-depths`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch queue depths: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch most recently created units for a plant from registry.
 */
export async function fetchRecentUnits(
  plantId: string,
  limit: number = 20,
  token?: string | null
): Promise<RecentUnitItem[]> {
  const baseUrl = getApiBaseUrl();
  const cleanPlantId = encodeURIComponent(plantId.trim());
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token.trim()}`;
  }
  const res = await fetch(`${baseUrl}/api/plants/${cleanPlantId}/units?limit=${limit}`, {
    cache: "no-store",
    headers,
  });

  if (res.status === 401) {
    throw new ApiError("Unauthorized", 401);
  }

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch recent units: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetch aggregated time-series history for a machine signal.
 */
export async function fetchSignalHistory(
  plantId: string,
  machineCode: string,
  signalCode: string,
  params: { start?: string; end?: string; points?: number } = {},
  token?: string | null
): Promise<SignalHistoryResponse> {
  const baseUrl = getApiBaseUrl();
  const cleanPlantId = encodeURIComponent(plantId.trim());
  const cleanMachine = encodeURIComponent(machineCode.trim());
  const cleanSignal = encodeURIComponent(signalCode.trim());

  const searchParams = new URLSearchParams();
  if (params.start) searchParams.set("start", params.start);
  if (params.end) searchParams.set("end", params.end);
  if (params.points !== undefined) searchParams.set("points", String(params.points));

  const queryStr = searchParams.toString();
  const url = `${baseUrl}/api/plants/${cleanPlantId}/machines/${cleanMachine}/signals/${cleanSignal}/history${
    queryStr ? `?${queryStr}` : ""
  }`;

  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token.trim()}`;
  }

  const res = await fetch(url, {
    cache: "no-store",
    headers,
  });

  if (res.status === 401) {
    throw new ApiError("Unauthorized", 401);
  }

  if (res.status === 404) {
    throw new ApiError(
      `Signal history not found for plant '${plantId}', machine '${machineCode}', signal '${signalCode}'`,
      404
    );
  }

  if (res.status === 400) {
    const errorData = await res.json().catch(() => ({}));
    throw new ApiError(
      errorData.detail || `Invalid history query parameters: ${res.statusText}`,
      400
    );
  }

  if (!res.ok) {
    throw new ApiError(
      `Failed to fetch signal history: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

