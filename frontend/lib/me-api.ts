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

export interface FastApiValidationErrorDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export class AdminApiError extends Error {
  status: number;
  validationErrors?: FastApiValidationErrorDetail[];

  constructor(message: string, status: number) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
  }
}

export interface SignalDefinition {
  signal_code: string;
  name: string;
  unit: string;
  data_type: "float" | "int" | "bool" | "string";
  display_order: number;
  normal_min: number | null;
  normal_max: number | null;
  warn_min: number | null;
  warn_max: number | null;
  alarm_min: number | null;
  alarm_max: number | null;
}

export interface MachineDefinition {
  machine_code: string;
  name: string;
  machine_type: string;
  display_order: number;
  signals: SignalDefinition[];
}

export interface AreaDefinition {
  area_code: string;
  name: string;
  display_order: number;
  machines: MachineDefinition[];
}

export interface OneTimeDeviceCredential {
  username: string;
  password?: string;
  client_id: string;
}

export interface AdminPlantDetail {
  plant_id: string;
  name: string;
  timezone: string;
  has_viewer_token: boolean;
  device_usernames: string[];
  areas: AreaDefinition[];
}

export interface MyPlantSummary {
  plant_id: string;
  name: string;
  timezone: string;
  has_viewer_token: boolean;
  role: string;
  created_at: string | null;
}

export interface AdminPlantCreatedResponse extends AdminPlantDetail {
  one_time_device_credentials?: OneTimeDeviceCredential[] | null;
  one_time_viewer_token?: string | null;
  viewer_token?: string | null;
  broker_reloaded?: boolean;
}

export interface AdminCredentialRotateResponse {
  plant_id: string;
  username: string;
  password: string;
  broker_reloaded: boolean;
}

export interface ViewerTokenRotateResponse {
  plant_id: string;
  viewer_token: string;
}

/**
 * Returns a human-readable quota string such as "1 of 3 plants".
 */
export function formatPlantQuota(count: number, max: number = 3): string {
  return `${count} of ${max} plants`;
}

/**
 * Checks whether the user can create another plant given current count and max quota.
 */
export function canCreatePlant(count: number, max: number = 3): boolean {
  return count < max;
}

/**
 * Generates an example JSON telemetry message matching the canonical schema from topic_router.py and ingest.py.
 */
export function buildTelemetryExampleJson(
  plantId: string,
  machineCode: string = "press_01",
  signalCode: string = "pressure_bar"
): string {
  const example = {
    schema_version: "1.0",
    plant_id: plantId,
    asset_id: machineCode,
    device_timestamp: new Date().toISOString(),
    message_id: "msg-001",
    payload: {
      status: "RUNNING",
      metrics: {
        [signalCode]: 42.0,
      },
    },
  };
  return JSON.stringify(example, null, 2);
}

/**
 * Generates the copy-paste docker compose exec broker mosquitto_pub command.
 * Uses exact topic plants/{plant_id}/assets/{machine_code}/telemetry with <password> placeholder.
 */
export function buildMosquittoPubCommand(
  plantId: string,
  machineCode: string = "press_01",
  signalCode: string = "pressure_bar"
): string {
  const jsonPayload = `{"schema_version":"1.0","plant_id":"${plantId}","asset_id":"${machineCode}","device_timestamp":"'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'","message_id":"msg-001","payload":{"status":"RUNNING","metrics":{"${signalCode}":42.0}}}`;
  return `docker compose exec broker mosquitto_pub -u device_${plantId} -P '<password>' -t 'plants/${plantId}/assets/${machineCode}/telemetry' -m '${jsonPayload}'`;
}

/**
 * Fetches plants belonging to the authenticated Clerk user.
 */
export async function fetchMyPlants(token: string): Promise<MyPlantSummary[]> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/me/plants`, {
    headers: {
      Authorization: `Bearer ${token.trim()}`,
    },
    cache: "no-store",
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new AdminApiError(
      errorBody.detail || `Failed to fetch user plants: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Fetches detail for a user-owned plant.
 */
export async function fetchMyPlantDetail(
  plantId: string,
  token: string
): Promise<AdminPlantDetail> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/me/plants/${encodeURIComponent(plantId)}`, {
    headers: {
      Authorization: `Bearer ${token.trim()}`,
    },
    cache: "no-store",
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new AdminApiError(
      errorBody.detail || `Failed to fetch plant detail: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Creates a new plant under /api/me/plants.
 */
export async function createMyPlant(
  token: string,
  payload: unknown
): Promise<AdminPlantCreatedResponse> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/me/plants`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token.trim()}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  if (!res.ok) {
    let rawJson: { detail?: string | FastApiValidationErrorDetail[] } = {};
    try {
      rawJson = await res.json();
    } catch {
      // ignore
    }
    let detailMsg = `Failed to create plant (${res.status})`;
    if (typeof rawJson.detail === "string") {
      detailMsg = rawJson.detail;
    } else if (Array.isArray(rawJson.detail)) {
      detailMsg = JSON.stringify(rawJson.detail);
    }
    const err = new AdminApiError(detailMsg, res.status);
    if (Array.isArray(rawJson.detail)) {
      err.validationErrors = rawJson.detail;
    }
    throw err;
  }

  return res.json();
}

/**
 * Rotates MQTT device credentials for a plant under /api/me/plants/{plant_id}/credentials/rotate.
 */
export async function rotateMyPlantCredentials(
  plantId: string,
  token: string
): Promise<AdminCredentialRotateResponse> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(
    `${baseUrl}/api/me/plants/${encodeURIComponent(plantId)}/credentials/rotate`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token.trim()}`,
      },
      cache: "no-store",
    }
  );

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new AdminApiError(
      errorBody.detail || `Failed to rotate credentials: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Rotates viewer token for a plant under /api/me/plants/{plant_id}/viewer-token/rotate.
 */
export async function rotateMyPlantViewerToken(
  plantId: string,
  token: string
): Promise<ViewerTokenRotateResponse> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(
    `${baseUrl}/api/me/plants/${encodeURIComponent(plantId)}/viewer-token/rotate`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token.trim()}`,
      },
      cache: "no-store",
    }
  );

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new AdminApiError(
      errorBody.detail || `Failed to rotate viewer token: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}

/**
 * Deletes a plant under /api/me/plants/{plant_id}.
 */
export async function deleteMyPlant(
  plantId: string,
  token: string
): Promise<{ status: string; plant_id: string; broker_reloaded?: boolean }> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(
    `${baseUrl}/api/me/plants/${encodeURIComponent(plantId)}`,
    {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${token.trim()}`,
      },
      cache: "no-store",
    }
  );

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new AdminApiError(
      errorBody.detail || `Failed to delete plant: ${res.statusText}`,
      res.status
    );
  }

  return res.json();
}
