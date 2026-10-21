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
