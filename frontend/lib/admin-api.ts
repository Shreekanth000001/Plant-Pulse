import type { AreaDefinition } from "../types/factory";

/**
 * Returns the sanitized base URL for API requests.
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

export interface AdminPlantSummary {
  plant_id: string;
  name: string;
  timezone: string;
  has_viewer_token: boolean;
}

export interface AdminPlantDetail {
  plant_id: string;
  name: string;
  timezone: string;
  has_viewer_token: boolean;
  device_usernames: string[];
  areas: AreaDefinition[];
}

/**
 * Redacts any occurrence of the bearer token or sensitive headers/parameters.
 */
export function redactSensitiveToken(text: string, knownToken?: string): string {
  let sanitized = text
    .replace(/Bearer\s+[A-Za-z0-9_\-.~+/]+=*/gi, "Bearer [REDACTED]")
    .replace(/ticket=[A-Za-z0-9_\-.~+/]+=*/gi, "ticket=[REDACTED]")
    .replace(/ADMIN_TOKEN=[^\s&'"]+/gi, "ADMIN_TOKEN=[REDACTED]");

  if (knownToken && knownToken.trim().length > 0) {
    const escaped = knownToken.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    sanitized = sanitized.replace(new RegExp(escaped, "g"), "[REDACTED]");
  }
  return sanitized;
}

export class AdminApiError extends Error {
  status: number;
  retryAfter?: number;
  isUnauthorized: boolean;
  isThrottled: boolean;
  isUnconfigured: boolean;
  isUnmounted: boolean;

  constructor(message: string, status: number, retryAfter?: number, sensitiveToken?: string) {
    const safeMessage = redactSensitiveToken(message, sensitiveToken);
    super(safeMessage);
    this.name = "AdminApiError";
    this.status = status;
    this.retryAfter = retryAfter;
    this.isUnauthorized = status === 401;
    this.isThrottled = status === 429;
    this.isUnconfigured = status === 503;
    this.isUnmounted = status === 404;
  }
}

/**
 * Maps any error or AdminApiError to a clear user-facing message.
 * Guaranteed never to leak tokens.
 */
export function formatAdminErrorMessage(err: unknown): string {
  if (err instanceof AdminApiError) {
    if (err.isUnauthorized) {
      return "Invalid admin token or unauthorized access. Please enter a valid token.";
    }
    if (err.isThrottled) {
      if (err.retryAfter && err.retryAfter > 0) {
        return `Too many failed attempts. Admin endpoints are locked out. Please wait ${err.retryAfter}s before retrying.`;
      }
      return "Too many failed attempts. Admin endpoints are temporarily locked out. Please wait before retrying.";
    }
    if (err.isUnconfigured) {
      return "Admin API disabled: ADMIN_TOKEN environment variable is not configured on the server.";
    }
    if (err.isUnmounted) {
      return "Admin endpoints are not mounted on this server (MOUNT_ADMIN_ENDPOINTS=false).";
    }
    if (err.status === 0) {
      return "Network failure: unable to connect to the backend server. Please verify your connection.";
    }
    return redactSensitiveToken(err.message);
  }

  if (err instanceof TypeError && /failed to fetch|network|fetch failed/i.test(err.message)) {
    return "Network failure: unable to connect to the backend server. Please verify your connection.";
  }

  if (err instanceof Error) {
    return redactSensitiveToken(err.message);
  }

  return "An unexpected error occurred while communicating with the admin API.";
}

/**
 * Checks whether the backend has admin endpoints mounted.
 * Sends a probe request to /api/admin/health without an auth token.
 * Returns false only if status is 404.
 */
export async function checkAdminMounted(customBaseUrl?: string): Promise<boolean> {
  const baseUrl = customBaseUrl || getApiBaseUrl();
  try {
    const res = await fetch(`${baseUrl}/api/admin/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    // 404 means the route does not exist (MOUNT_ADMIN_ENDPOINTS=false)
    return res.status !== 404;
  } catch {
    // If backend is unreachable, we treat it as reachable network issue rather than unmounted
    return true;
  }
}

/**
 * Performs authenticated health check with the given admin token.
 */
export async function checkAdminHealth(
  token: string,
  customBaseUrl?: string
): Promise<{ ok: boolean; status: string }> {
  const baseUrl = customBaseUrl || getApiBaseUrl();
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/admin/health`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
      },
    });
  } catch (netErr) {
    throw new AdminApiError(
      `Network failure connecting to admin health check: ${netErr instanceof Error ? netErr.message : String(netErr)}`,
      0,
      undefined,
      token
    );
  }

  if (!res.ok) {
    let retryAfter: number | undefined;
    const retryHeader = res.headers.get("Retry-After");
    if (retryHeader) {
      const parsed = parseInt(retryHeader, 10);
      if (!Number.isNaN(parsed)) retryAfter = parsed;
    }

    let detail = `Admin health check failed (${res.status})`;
    try {
      const json = await res.json();
      if (json && typeof json.detail === "string") {
        detail = json.detail;
      }
    } catch {
      // ignore json decode failure
    }

    throw new AdminApiError(detail, res.status, retryAfter, token);
  }

  const data = await res.json();
  return { ok: true, status: data.status || "ok" };
}

/**
 * Fetches the summary list of all registered plants.
 */
export async function fetchAdminPlants(
  token: string,
  customBaseUrl?: string
): Promise<AdminPlantSummary[]> {
  const baseUrl = customBaseUrl || getApiBaseUrl();
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/admin/plants`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
      },
    });
  } catch (netErr) {
    throw new AdminApiError(
      `Network failure fetching admin plants: ${netErr instanceof Error ? netErr.message : String(netErr)}`,
      0,
      undefined,
      token
    );
  }

  if (!res.ok) {
    let retryAfter: number | undefined;
    const retryHeader = res.headers.get("Retry-After");
    if (retryHeader) {
      const parsed = parseInt(retryHeader, 10);
      if (!Number.isNaN(parsed)) retryAfter = parsed;
    }

    let detail = `Failed to fetch admin plants (${res.status})`;
    try {
      const json = await res.json();
      if (json && typeof json.detail === "string") {
        detail = json.detail;
      }
    } catch {
      // ignore json decode failure
    }

    throw new AdminApiError(detail, res.status, retryAfter, token);
  }

  return (await res.json()) as AdminPlantSummary[];
}

/**
 * Fetches full detail for a single plant by ID.
 */
export async function fetchAdminPlantDetail(
  plantId: string,
  token: string,
  customBaseUrl?: string
): Promise<AdminPlantDetail> {
  const baseUrl = customBaseUrl || getApiBaseUrl();
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/admin/plants/${encodeURIComponent(plantId.trim())}`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
      },
    });
  } catch (netErr) {
    throw new AdminApiError(
      `Network failure fetching plant detail: ${netErr instanceof Error ? netErr.message : String(netErr)}`,
      0,
      undefined,
      token
    );
  }

  if (!res.ok) {
    let retryAfter: number | undefined;
    const retryHeader = res.headers.get("Retry-After");
    if (retryHeader) {
      const parsed = parseInt(retryHeader, 10);
      if (!Number.isNaN(parsed)) retryAfter = parsed;
    }

    let detail = `Failed to fetch plant detail (${res.status})`;
    try {
      const json = await res.json();
      if (json && typeof json.detail === "string") {
        detail = json.detail;
      }
    } catch {
      // ignore json decode failure
    }

    throw new AdminApiError(detail, res.status, retryAfter, token);
  }

  return (await res.json()) as AdminPlantDetail;
}

export interface OneTimeDeviceCredential {
  username: string;
  password?: string;
  client_id: string;
}

export interface AdminPlantCreatedResponse extends AdminPlantDetail {
  one_time_device_credentials?: OneTimeDeviceCredential[];
  broker_reloaded?: boolean;
}

export interface AdminCredentialRotationResponse {
  username: string;
  password?: string;
  client_id: string;
  broker_reloaded?: boolean;
}

export interface FastApiValidationErrorDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface CredentialModalState {
  isOpen: boolean;
  credentials: OneTimeDeviceCredential[] | null;
  source: "create" | "rotate" | null;
  brokerReloaded?: boolean;
}

export const initialCredentialModalState: CredentialModalState = {
  isOpen: false,
  credentials: null,
  source: null,
};

export type CredentialModalAction =
  | {
      type: "OPEN_CREDENTIALS";
      source: "create" | "rotate";
      credentials: OneTimeDeviceCredential[];
      brokerReloaded?: boolean;
    }
  | { type: "CLOSE_CREDENTIALS" };

export function credentialModalReducer(
  state: CredentialModalState,
  action: CredentialModalAction
): CredentialModalState {
  switch (action.type) {
    case "OPEN_CREDENTIALS":
      return {
        isOpen: true,
        credentials: action.credentials,
        source: action.source,
        brokerReloaded: action.brokerReloaded,
      };
    case "CLOSE_CREDENTIALS":
      return {
        isOpen: false,
        credentials: null,
        source: null,
        brokerReloaded: undefined,
      };
    default:
      return state;
  }
}

/**
 * Maps FastAPI 422 validation error array into a flat field error map.
 * E.g. loc: ["body", "areas", 0, "machines", 1, "machine_code"] -> "areas.0.machines.1.machine_code"
 */
export function mapFastApi422Errors(details: unknown): Record<string, string> {
  const result: Record<string, string> = {};
  if (!Array.isArray(details)) return result;

  for (const item of details) {
    if (!item || typeof item !== "object") continue;
    const detail = item as Partial<FastApiValidationErrorDetail>;
    if (!Array.isArray(detail.loc) || typeof detail.msg !== "string") continue;

    const locParts = detail.loc[0] === "body" ? detail.loc.slice(1) : detail.loc;
    const fieldPath = locParts.join(".");
    if (fieldPath) {
      result[fieldPath] = detail.msg;
    }
  }

  return result;
}

/**
 * Creates a new plant definition on the backend.
 */
export async function createAdminPlant(
  token: string,
  payload: Record<string, unknown>,
  customBaseUrl?: string
): Promise<AdminPlantCreatedResponse> {
  const baseUrl = customBaseUrl || getApiBaseUrl();
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/admin/plants`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch (netErr) {
    throw new AdminApiError(
      `Network failure creating plant: ${netErr instanceof Error ? netErr.message : String(netErr)}`,
      0,
      undefined,
      token
    );
  }

  if (!res.ok) {
    let retryAfter: number | undefined;
    const retryHeader = res.headers.get("Retry-After");
    if (retryHeader) {
      const parsed = parseInt(retryHeader, 10);
      if (!Number.isNaN(parsed)) retryAfter = parsed;
    }

    let detail = `Failed to create plant (${res.status})`;
    let rawJson: { detail?: string | FastApiValidationErrorDetail[] } | undefined;
    try {
      rawJson = await res.json();
      if (rawJson && typeof rawJson.detail === "string") {
        detail = rawJson.detail;
      } else if (rawJson && Array.isArray(rawJson.detail)) {
        detail = JSON.stringify(rawJson.detail);
      }
    } catch {
      // ignore
    }

    const err = new AdminApiError(detail, res.status, retryAfter, token);
    (err as unknown as { validationErrors?: FastApiValidationErrorDetail[] }).validationErrors =
      rawJson && Array.isArray(rawJson.detail) ? rawJson.detail : undefined;
    throw err;
  }

  return (await res.json()) as AdminPlantCreatedResponse;
}

/**
 * Rotates device credentials for a registered plant.
 */
export async function rotateAdminDeviceCredentials(
  token: string,
  plantId: string,
  customBaseUrl?: string
): Promise<AdminCredentialRotationResponse> {
  const baseUrl = customBaseUrl || getApiBaseUrl();
  let res: Response;
  try {
    res = await fetch(
      `${baseUrl}/api/admin/plants/${encodeURIComponent(plantId.trim())}/credentials/rotate`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/json",
        },
      }
    );
  } catch (netErr) {
    throw new AdminApiError(
      `Network failure rotating device credentials: ${netErr instanceof Error ? netErr.message : String(netErr)}`,
      0,
      undefined,
      token
    );
  }

  if (!res.ok) {
    let retryAfter: number | undefined;
    const retryHeader = res.headers.get("Retry-After");
    if (retryHeader) {
      const parsed = parseInt(retryHeader, 10);
      if (!Number.isNaN(parsed)) retryAfter = parsed;
    }

    let detail = `Failed to rotate device credentials (${res.status})`;
    try {
      const json = await res.json();
      if (json && typeof json.detail === "string") {
        detail = json.detail;
      }
    } catch {
      // ignore
    }

    throw new AdminApiError(detail, res.status, retryAfter, token);
  }

  return (await res.json()) as AdminCredentialRotationResponse;
}

/**
 * Updates an existing plant definition.
 */
export async function updateAdminPlant(
  token: string,
  plantId: string,
  payload: Record<string, unknown>,
  confirmRemovals = false,
  customBaseUrl?: string
): Promise<AdminPlantDetail> {
  const baseUrl = customBaseUrl || getApiBaseUrl();
  const queryParam = confirmRemovals ? "?confirm_removals=true" : "";
  let res: Response;
  try {
    res = await fetch(
      `${baseUrl}/api/admin/plants/${encodeURIComponent(plantId.trim())}${queryParam}`,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      }
    );
  } catch (netErr) {
    throw new AdminApiError(
      `Network failure updating plant: ${netErr instanceof Error ? netErr.message : String(netErr)}`,
      0,
      undefined,
      token
    );
  }

  if (!res.ok) {
    let retryAfter: number | undefined;
    const retryHeader = res.headers.get("Retry-After");
    if (retryHeader) {
      const parsed = parseInt(retryHeader, 10);
      if (!Number.isNaN(parsed)) retryAfter = parsed;
    }

    let detail = `Failed to update plant (${res.status})`;
    let rawJson: { detail?: string | FastApiValidationErrorDetail[] } | undefined;
    try {
      rawJson = await res.json();
      if (rawJson && typeof rawJson.detail === "string") {
        detail = rawJson.detail;
      } else if (rawJson && Array.isArray(rawJson.detail)) {
        detail = JSON.stringify(rawJson.detail);
      }
    } catch {
      // ignore
    }

    const err = new AdminApiError(detail, res.status, retryAfter, token);
    (err as unknown as { validationErrors?: FastApiValidationErrorDetail[] }).validationErrors =
      rawJson && Array.isArray(rawJson.detail) ? rawJson.detail : undefined;
    throw err;
  }

  return (await res.json()) as AdminPlantDetail;
}

export const SYSTEM_PLANT_IDS = new Set<string>(["plant_demo_membrane"]);

export function isSystemPlant(plantId: string): boolean {
  if (!plantId) return false;
  return SYSTEM_PLANT_IDS.has(plantId.trim());
}

export function canConfirmDelete(
  targetPlantId: string,
  inputPlantId: string,
  isProtectedSystemPlant?: boolean
): boolean {
  if (isProtectedSystemPlant) return false;
  if (!targetPlantId || !inputPlantId) return false;
  return targetPlantId.trim() === inputPlantId.trim();
}

export interface PlantRemovalsDiff {
  removedAreas: string[];
  removedMachines: string[];
  removedSignals: string[];
  hasRemovals: boolean;
}

export function diffPlantRemovals(
  originalPlant: {
    areas?: Array<{
      area_code: string;
      machines?: Array<{
        machine_code: string;
        signals?: Array<{ signal_code: string }>;
      }>;
    }>;
  },
  updatedPlant: {
    areas?: Array<{
      area_code: string;
      machines?: Array<{
        machine_code: string;
        signals?: Array<{ signal_code: string }>;
      }>;
    }>;
  }
): PlantRemovalsDiff {
  const origAreas = new Set((originalPlant.areas || []).map((a) => a.area_code));
  const newAreas = new Set((updatedPlant.areas || []).map((a) => a.area_code));
  const removedAreas = Array.from(origAreas).filter((a) => !newAreas.has(a)).sort();

  const origMachines = new Set(
    (originalPlant.areas || []).flatMap((a) => (a.machines || []).map((m) => m.machine_code))
  );
  const newMachines = new Set(
    (updatedPlant.areas || []).flatMap((a) => (a.machines || []).map((m) => m.machine_code))
  );
  const removedMachines = Array.from(origMachines).filter((m) => !newMachines.has(m)).sort();

  const origSignals = new Set(
    (originalPlant.areas || []).flatMap((a) =>
      (a.machines || []).flatMap((m) =>
        (m.signals || []).map((s) => `${m.machine_code}:${s.signal_code}`)
      )
    )
  );
  const newSignals = new Set(
    (updatedPlant.areas || []).flatMap((a) =>
      (a.machines || []).flatMap((m) =>
        (m.signals || []).map((s) => `${m.machine_code}:${s.signal_code}`)
      )
    )
  );
  const removedSignals = Array.from(origSignals).filter((s) => !newSignals.has(s)).sort();

  const hasRemovals =
    removedAreas.length > 0 || removedMachines.length > 0 || removedSignals.length > 0;

  return {
    removedAreas,
    removedMachines,
    removedSignals,
    hasRemovals,
  };
}

export interface Parsed409Removals {
  removedAreas: string[];
  removedMachines: string[];
  removedSignals: string[];
  isRemovalConflict: boolean;
}

export function parse409Removals(detail: string): Parsed409Removals {
  if (!detail || typeof detail !== "string") {
    return {
      removedAreas: [],
      removedMachines: [],
      removedSignals: [],
      isRemovalConflict: false,
    };
  }

  const isRemovalConflict =
    detail.includes("Updating plant would remove existing components") ||
    detail.includes("confirm_removals=true");

  const parseList = (regex: RegExp): string[] => {
    const match = detail.match(regex);
    if (!match || !match[1]) return [];
    return match[1]
      .split(",")
      .map((s) => s.replace(/['"\[\]]/g, "").trim())
      .filter((s) => s.length > 0);
  };

  const removedAreas = parseList(/areas:\s*\[(.*?)\]/);
  const removedMachines = parseList(/machines:\s*\[(.*?)\]/);
  const removedSignals = parseList(/signals:\s*\[(.*?)\]/);

  return {
    removedAreas,
    removedMachines,
    removedSignals,
    isRemovalConflict:
      isRemovalConflict ||
      removedAreas.length > 0 ||
      removedMachines.length > 0 ||
      removedSignals.length > 0,
  };
}

export interface AdminPlantDeleteResponse {
  status: "deleted";
  plant_id: string;
  broker_reloaded: boolean;
}

export async function deleteAdminPlant(
  token: string,
  plantId: string,
  customBaseUrl?: string
): Promise<AdminPlantDeleteResponse> {
  const baseUrl = customBaseUrl || getApiBaseUrl();
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api/admin/plants/${encodeURIComponent(plantId.trim())}`, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
      },
    });
  } catch (netErr) {
    throw new AdminApiError(
      `Network failure deleting plant: ${netErr instanceof Error ? netErr.message : String(netErr)}`,
      0,
      undefined,
      token
    );
  }

  if (!res.ok) {
    let retryAfter: number | undefined;
    const retryHeader = res.headers.get("Retry-After");
    if (retryHeader) {
      const parsed = parseInt(retryHeader, 10);
      if (!Number.isNaN(parsed)) retryAfter = parsed;
    }

    let detail = `Failed to delete plant (${res.status})`;
    try {
      const json = await res.json();
      if (json && typeof json.detail === "string") {
        detail = json.detail;
      }
    } catch {
      // ignore json decode failure
    }

    throw new AdminApiError(detail, res.status, retryAfter, token);
  }

  return (await res.json()) as AdminPlantDeleteResponse;
}

export interface PlantJsonParseResult {
  success: boolean;
  data: Record<string, unknown> | null;
  error: string | null;
  line?: number;
  column?: number;
}

export function parsePlantJson(jsonString: string): PlantJsonParseResult {
  if (!jsonString || typeof jsonString !== "string" || !jsonString.trim()) {
    return {
      success: false,
      data: null,
      error: "JSON string is empty",
    };
  }

  try {
    const data = JSON.parse(jsonString);
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return {
        success: false,
        data: null,
        error: "Root JSON value must be an object (plant definition).",
      };
    }
    return {
      success: true,
      data: data as Record<string, unknown>,
      error: null,
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    let line: number | undefined;
    let column: number | undefined;

    const lineColMatch = msg.match(/line\s+(\d+)\s+column\s+(\d+)/i);
    if (lineColMatch) {
      line = parseInt(lineColMatch[1], 10);
      column = parseInt(lineColMatch[2], 10);
    } else {
      const posMatch = msg.match(/position\s+(\d+)/i);
      if (posMatch) {
        const pos = parseInt(posMatch[1], 10);
        const prefix = jsonString.slice(0, pos);
        const lines = prefix.split("\n");
        line = lines.length;
        column = lines[lines.length - 1].length + 1;
      }
    }

    const posStr =
      line !== undefined && column !== undefined
        ? ` at line ${line}, column ${column}`
        : line !== undefined
          ? ` at line ${line}`
          : "";

    return {
      success: false,
      data: null,
      error: `Syntax error${posStr}: ${msg}`,
      line,
      column,
    };
  }
}

export interface AdvisoryValidationResult {
  valid: boolean;
  errors: Record<string, string>;
  warnings: string[];
}

export function validatePlantDefinitionAdvisory(data: unknown): AdvisoryValidationResult {
  const errors: Record<string, string> = {};
  const warnings: string[] = [];

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return {
      valid: false,
      errors: { root: "Plant definition must be an object." },
      warnings,
    };
  }

  const obj = data as Record<string, unknown>;

  // plant_id validation
  const plantId = obj.plant_id;
  if (!plantId || typeof plantId !== "string" || !plantId.trim()) {
    errors["plant_id"] = "Field required";
  } else if (!/^[a-z0-9_]{3,64}$/.test(plantId.trim())) {
    errors["plant_id"] = "String should match pattern '^[a-z0-9_]{3,64}$'";
  }

  // name validation
  if (!obj.name || typeof obj.name !== "string" || !obj.name.trim()) {
    errors["name"] = "Field required";
  }

  // areas validation
  if (!obj.areas || !Array.isArray(obj.areas)) {
    errors["areas"] = "Areas list is required and must be an array.";
  } else if (obj.areas.length === 0) {
    warnings.push("Plant has no production areas configured.");
  } else {
    const areaCodes = new Set<string>();

    obj.areas.forEach((areaRaw, aIdx) => {
      if (!areaRaw || typeof areaRaw !== "object") {
        errors[`areas.${aIdx}`] = "Area must be an object.";
        return;
      }
      const area = areaRaw as Record<string, unknown>;
      const aCode = String(area.area_code || "").trim();
      if (!aCode) {
        errors[`areas.${aIdx}.area_code`] = "Area code is required.";
      } else if (areaCodes.has(aCode)) {
        errors[`areas.${aIdx}.area_code`] = `Duplicate area code '${aCode}'.`;
      } else {
        areaCodes.add(aCode);
      }

      if (!area.machines || !Array.isArray(area.machines)) {
        warnings.push(`Area '${aCode || aIdx}' has no machines array.`);
      } else {
        const machCodes = new Set<string>();
        area.machines.forEach((machRaw, mIdx) => {
          if (!machRaw || typeof machRaw !== "object") return;
          const mach = machRaw as Record<string, unknown>;
          const mCode = String(mach.machine_code || "").trim();
          if (!mCode) {
            errors[`areas.${aIdx}.machines.${mIdx}.machine_code`] = "Machine code is required.";
          } else if (machCodes.has(mCode)) {
            errors[`areas.${aIdx}.machines.${mIdx}.machine_code`] =
              `Duplicate machine code '${mCode}'.`;
          } else {
            machCodes.add(mCode);
          }

          if (mach.signals && Array.isArray(mach.signals)) {
            const sigCodesInMach = new Set<string>();
            mach.signals.forEach((sigRaw, sIdx) => {
              if (!sigRaw || typeof sigRaw !== "object") return;
              const sig = sigRaw as Record<string, unknown>;
              const sCode = String(sig.signal_code || "").trim();
              if (!sCode) {
                errors[`areas.${aIdx}.machines.${mIdx}.signals.${sIdx}.signal_code`] =
                  "Signal code is required.";
              } else if (sigCodesInMach.has(sCode)) {
                errors[`areas.${aIdx}.machines.${mIdx}.signals.${sIdx}.signal_code`] =
                  `Duplicate signal code '${sCode}' in machine '${mCode}'.`;
              } else {
                sigCodesInMach.add(sCode);
              }
            });
          }
        });
      }
    });
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
    warnings,
  };
}

export function exportPlantDefinitionJson(plant: unknown): string {
  if (!plant || typeof plant !== "object") {
    return "{}";
  }

  const p = plant as Record<string, unknown>;

  const clean: Record<string, unknown> = {
    plant_id: p.plant_id || "",
    name: p.name || "",
    timezone: p.timezone || "UTC",
    enabled_modules: Array.isArray(p.enabled_modules) ? p.enabled_modules : ["core", "alarms"],
  };

  if (Array.isArray(p.areas)) {
    clean.areas = p.areas.map((areaRaw: unknown, aIdx: number) => {
      const area = (areaRaw || {}) as Record<string, unknown>;
      return {
        area_code: area.area_code || "",
        name: area.name || "",
        display_order: typeof area.display_order === "number" ? area.display_order : aIdx + 1,
        machines: Array.isArray(area.machines)
          ? area.machines.map((machRaw: unknown, mIdx: number) => {
              const mach = (machRaw || {}) as Record<string, unknown>;
              return {
                machine_code: mach.machine_code || "",
                name: mach.name || "",
                machine_type: mach.machine_type || "standard",
                display_order:
                  typeof mach.display_order === "number" ? mach.display_order : mIdx + 1,
                signals: Array.isArray(mach.signals)
                  ? mach.signals.map((sigRaw: unknown, sIdx: number) => {
                      const sig = (sigRaw || {}) as Record<string, unknown>;
                      return {
                        signal_code: sig.signal_code || "",
                        name: sig.name || "",
                        unit: sig.unit || "",
                        data_type: sig.data_type || "float",
                        is_setpoint: Boolean(sig.is_setpoint),
                        setpoint_signal_code: sig.setpoint_signal_code || null,
                        normal_min: sig.normal_min ?? null,
                        normal_max: sig.normal_max ?? null,
                        warn_min: sig.warn_min ?? null,
                        warn_max: sig.warn_max ?? null,
                        alarm_min: sig.alarm_min ?? null,
                        alarm_max: sig.alarm_max ?? null,
                        display_order:
                          typeof sig.display_order === "number" ? sig.display_order : sIdx + 1,
                      };
                    })
                  : [],
              };
            })
          : [],
      };
    });
  } else {
    clean.areas = [];
  }

  // Explicit defense against secret key leaks
  delete clean.viewer_token;
  delete clean.viewer_token_hash;
  delete clean.password;
  delete clean.password_hash;
  delete clean.mqtt_credentials;
  delete clean.device_usernames;

  return JSON.stringify(clean, null, 2);
}




