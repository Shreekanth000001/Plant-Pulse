"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
} from "react";
import {
  getWsUrl,
  fetchQueueDepths,
  fetchPlants,
  fetchPlantDefinition,
  fetchPlantMachinesLatest,
} from "../lib/api";
import {
  safeLocalStorageGet,
  safeLocalStorageSet,
  handleWsCloseState,
} from "../lib/plant-utils";
import type {
  WebSocketMessage,
  QCResultPayload,
  QueueHandoffs,
  BackendQueueDepths,
  MachineStatus,
  PlantSummary,
  PublicPlantDefinition,
  PlantMachineLatest,
  Readings,
} from "../types/factory";
import {
  mapBackendQueueDepths,
  isTelemetryMessage,
  isReadingValue,
} from "../types/factory";

export type ConnectionStatus =
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "token_required";

export interface QCNotification {
  id: string;
  unit_id: string;
  outcome: "pass" | "fail";
  defect_type?: string | null;
  attributed_stage?: string | null;
  probability?: number;
  timestamp: string;
}

interface WebSocketContextType {
  selectedPlantId: string;
  selectPlant: (plantId: string) => void;
  plantsList: PlantSummary[];
  plantDefinition: PublicPlantDefinition | null;
  machinesLatest: PlantMachineLatest[];
  status: ConnectionStatus;
  reconnectAttempt: number;
  lastMessageAt: string | null;
  handoffs: QueueHandoffs;
  machines: Record<string, MachineStatus>;
  recentQcResults: QCNotification[];
  dismissNotification: (id: string) => void;
  subscribeToTelemetry: (
    callback: (message: WebSocketMessage) => void
  ) => () => void;
  isTokenRequired: boolean;
  pollingActive: boolean;
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

const MAX_RECONNECT_DELAY_MS = 15000;
const INITIAL_RECONNECT_DELAY_MS = 1500;
const DEFAULT_PLANT_ID = "plant_demo_membrane";

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [selectedPlantId, setSelectedPlantId] = useState<string>(() =>
    safeLocalStorageGet("plantpulse_active_plant", DEFAULT_PLANT_ID)
  );
  const [plantsList, setPlantsList] = useState<PlantSummary[]>([]);
  const [plantDefinition, setPlantDefinition] =
    useState<PublicPlantDefinition | null>(null);
  const [machinesLatest, setMachinesLatest] = useState<PlantMachineLatest[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const [lastMessageAt, setLastMessageAt] = useState<string | null>(null);
  const [recentQcResults, setRecentQcResults] = useState<QCNotification[]>([]);
  const [handoffs, setHandoffs] = useState<QueueHandoffs>({
    housingToCasting: 0,
    castingToAssembly: 0,
    assemblyToQc: 0,
  });
  const [machines, setMachines] = useState<Record<string, MachineStatus>>({});
  const [isTokenRequired, setIsTokenRequired] = useState(false);
  const [pollingActive, setPollingActive] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY_MS);
  const isCleanedUpRef = useRef(false);
  const subscribersRef = useRef<Set<(message: WebSocketMessage) => void>>(
    new Set()
  );

  const selectPlant = useCallback((plantId: string) => {
    setSelectedPlantId(plantId);
    safeLocalStorageSet("plantpulse_active_plant", plantId);
  }, []);

  const dismissNotification = useCallback((id: string) => {
    setRecentQcResults((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const subscribeToTelemetry = useCallback(
    (callback: (message: WebSocketMessage) => void) => {
      subscribersRef.current.add(callback);
      return () => {
        subscribersRef.current.delete(callback);
      };
    },
    []
  );

  // 1. Fetch plants list on mount
  useEffect(() => {
    let active = true;
    fetchPlants()
      .then((data) => {
        if (active) setPlantsList(data);
      })
      .catch((err) => {
        console.warn("Failed to fetch plants list:", err);
      });
    return () => {
      active = false;
    };
  }, []);

  // 2. Main plant sync effect (runs whenever selectedPlantId changes)
  useEffect(() => {
    isCleanedUpRef.current = false;
    let isCurrent = true;

    // Reset plant-specific state
    queueMicrotask(() => {
      if (!isCurrent) return;
      setStatus("disconnected");
      setIsTokenRequired(false);
      setPollingActive(false);
      setReconnectAttempt(0);
    });
    reconnectDelayRef.current = INITIAL_RECONNECT_DELAY_MS;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    // Function to poll REST endpoint
    const pollLatestMachines = async () => {
      try {
        const latest = await fetchPlantMachinesLatest(selectedPlantId);
        if (!isCurrent) return;
        setMachinesLatest(latest);
        setMachines((prev) => {
          const next = { ...prev };
          for (const m of latest) {
            const existing = next[m.machine_code] || {
              machine_id: m.machine_code,
              name: m.name,
              area_code: m.area_code,
              sub_facility: m.area_code,
              machine_state: m.state,
              phase: m.sub_state,
              starved: false,
              signals: m.signals || {},
              extra: {},
            };
            next[m.machine_code] = {
              ...existing,
              name: m.name,
              machine_state: m.state,
              phase: m.sub_state,
              signals: m.signals || {},
            };
          }
          return next;
        });
        setLastMessageAt(new Date().toISOString());
      } catch (err) {
        console.warn("Error polling machines latest:", err);
      }
    };

    // Load definition and initial machines
    const initPlant = async () => {
      try {
        const [def, latest] = await Promise.all([
          fetchPlantDefinition(selectedPlantId).catch(() => null),
          fetchPlantMachinesLatest(selectedPlantId).catch(() => []),
        ]);
        if (!isCurrent) return;

        if (def) {
          setPlantDefinition(def);
          const initialMachines: Record<string, MachineStatus> = {};
          const latestMap = new Map<string, PlantMachineLatest>();
          for (const m of latest) {
            latestMap.set(m.machine_code, m);
          }

          for (const area of def.areas || []) {
            for (const m of area.machines || []) {
              const snap = latestMap.get(m.machine_code);
              initialMachines[m.machine_code] = {
                machine_id: m.machine_code,
                name: m.name,
                area_code: area.area_code,
                sub_facility: area.area_code,
                machine_state: snap?.state || "IDLE",
                phase: snap?.sub_state || null,
                starved: false,
                good_count: 0,
                reject_count: 0,
                signals: snap?.signals || {},
                extra: {},
              };
            }
          }
          setMachines(initialMachines);
        }

        if (latest && latest.length > 0) {
          setMachinesLatest(latest);
        }

        // Fetch queue depths if plant has product_traceability enabled
        if (def && def.enabled_modules?.includes("product_traceability")) {
          fetchQueueDepths()
            .then((depths) => {
              if (isCurrent && depths) {
                setHandoffs(mapBackendQueueDepths(depths));
              }
            })
            .catch(() => {});
        }
      } catch (err) {
        console.warn("Failed to initialize plant definition:", err);
      }
    };

    initPlant();

    // Establish WebSocket connection
    const connectWs = () => {
      if (typeof window === "undefined" || isCleanedUpRef.current) return;

      const wsUrl = getWsUrl(selectedPlantId);
      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isCurrent) return;
          setStatus("connected");
          setIsTokenRequired(false);
          setReconnectAttempt(0);
          reconnectDelayRef.current = INITIAL_RECONNECT_DELAY_MS;
        };

        ws.onmessage = (event) => {
          if (!isCurrent) return;
          try {
            const raw = JSON.parse(event.data) as WebSocketMessage;
            setLastMessageAt(new Date().toISOString());

            // Notify subscribers
            subscribersRef.current.forEach((cb) => {
              try {
                cb(raw);
              } catch (err) {
                console.error("Subscriber callback error:", err);
              }
            });

            const topic = raw.topic || "";

            // 1. Multi-plant assets telemetry: plants/{plant_id}/assets/{machine_code}/telemetry
            if (topic.includes("/assets/") && topic.endsWith("/telemetry")) {
              const parts = topic.split("/");
              const machineCode = parts[3];
              const payload = (raw.payload || {}) as Record<string, unknown>;
              const readingsObj =
                (payload.readings as Record<string, unknown>) || payload;

              setMachines((prev) => {
                const existing = prev[machineCode];
                if (!existing) return prev;

                const mergedExtra: Readings = { ...(existing.extra || {}) };
                for (const [k, v] of Object.entries(readingsObj)) {
                  if (isReadingValue(v)) {
                    mergedExtra[k] = v;
                  }
                }

                // If readings has vibration, update vibration property
                const vib =
                  typeof readingsObj.vibration_rms_mms === "number"
                    ? readingsObj.vibration_rms_mms
                    : typeof readingsObj.vibration === "number"
                    ? readingsObj.vibration
                    : typeof readingsObj.vibration_mms === "number"
                    ? readingsObj.vibration_mms
                    : existing.vibration;

                return {
                  ...prev,
                  [machineCode]: {
                    ...existing,
                    vibration: vib,
                    extra: mergedExtra,
                    timestamp: new Date().toISOString(),
                  },
                };
              });
            }
            // 2. Machine state topic: plants/{plant_id}/assets/{machine_code}/state
            else if (topic.includes("/assets/") && topic.endsWith("/state")) {
              const parts = topic.split("/");
              const machineCode = parts[3];
              const payload = (raw.payload || {}) as Record<string, unknown>;
              const state = (payload.state as string) || "IDLE";
              const subState = payload.sub_state as string | undefined;

              setMachines((prev) => {
                const existing = prev[machineCode];
                if (!existing) return prev;
                return {
                  ...prev,
                  [machineCode]: {
                    ...existing,
                    machine_state: state,
                    phase: subState !== undefined ? subState : existing.phase,
                  },
                };
              });
            }
            // 3. Queue depths topic
            else if (topic.includes("/queue_depths")) {
              const depths = raw.payload as BackendQueueDepths;
              setHandoffs(mapBackendQueueDepths(depths));
            }
            // 4. QC Result topic: plants/{plant_id}/modules/quality/qc_result or legacy .../result
            else if (topic.includes("/qc_result") || topic.endsWith("/result")) {
              const qcPayload = raw.payload as QCResultPayload;
              const uniqueSuffix = Math.random().toString(36).substring(2, 8);
              const newNotification: QCNotification = {
                id: `${qcPayload.unit_id}-${Date.now()}-${uniqueSuffix}`,
                unit_id: qcPayload.unit_id,
                outcome: qcPayload.outcome,
                defect_type: qcPayload.defect_type,
                attributed_stage: qcPayload.attributed_stage,
                probability: qcPayload.probability,
                timestamp: new Date().toLocaleTimeString(),
              };

              setRecentQcResults((prev) => {
                if (prev.some((item) => item.unit_id === qcPayload.unit_id)) {
                  return prev;
                }
                return [newNotification, ...prev.slice(0, 4)];
              });
            }
            // 5. Legacy telemetry topics: factory/{subFacility}/{machineId}/telemetry
            else if (isTelemetryMessage(raw)) {
              const parts = topic.split("/");
              if (parts.length >= 4) {
                const machineId = parts[2];
                const payload = (raw.payload || {}) as Record<string, unknown>;

                setMachines((prev) => {
                  const existing = prev[machineId];
                  if (!existing) return prev;
                  return {
                    ...prev,
                    [machineId]: {
                      ...existing,
                      machine_state:
                        (payload.machine_state as string) ||
                        existing.machine_state,
                      phase:
                        payload.phase !== undefined
                          ? (payload.phase as string)
                          : existing.phase,
                      starved:
                        payload.starved !== undefined
                          ? Boolean(payload.starved)
                          : existing.starved,
                      current_unit_id:
                        (payload.current_unit_id as string) ||
                        existing.current_unit_id,
                      vibration:
                        payload.vibration !== undefined
                          ? (payload.vibration as number)
                          : existing.vibration,
                      good_count:
                        payload.good_count !== undefined
                          ? (payload.good_count as number)
                          : existing.good_count,
                      reject_count:
                        payload.reject_count !== undefined
                          ? (payload.reject_count as number)
                          : existing.reject_count,
                    },
                  };
                });
              }
            }
          } catch (e) {
            console.warn("Failed to parse incoming WebSocket message:", e);
          }
        };

        ws.onerror = () => {};

        ws.onclose = (event) => {
          if (isCleanedUpRef.current || !isCurrent) return;

          const handling = handleWsCloseState(event.code);
          setStatus(handling.status);
          setIsTokenRequired(handling.isTokenRequired);

          if (handling.isTokenRequired) {
            // Do not reconnect to WebSocket. Activate 5s REST polling fallback!
            setPollingActive(true);
            pollLatestMachines(); // immediate fetch
            if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = setInterval(
              pollLatestMachines,
              handling.fallbackPollingIntervalMs || 5000
            );
            return;
          }

          // Otherwise exponential backoff reconnect for normal disconnected states
          setReconnectAttempt((prev) => prev + 1);
          const delay = reconnectDelayRef.current;
          reconnectDelayRef.current = Math.min(
            reconnectDelayRef.current * 1.5,
            MAX_RECONNECT_DELAY_MS
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            if (!isCleanedUpRef.current && isCurrent) {
              connectWs();
            }
          }, delay);
        };
      } catch {
        if (isCurrent) setStatus("disconnected");
      }
    };

    connectWs();

    return () => {
      isCleanedUpRef.current = true;
      isCurrent = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [selectedPlantId]);

  return (
    <WebSocketContext.Provider
      value={{
        selectedPlantId,
        selectPlant,
        plantsList,
        plantDefinition,
        machinesLatest,
        status,
        reconnectAttempt,
        lastMessageAt,
        handoffs,
        machines,
        recentQcResults,
        dismissNotification,
        subscribeToTelemetry,
        isTokenRequired,
        pollingActive,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
}

export function useFactoryWebSocket() {
  const ctx = useContext(WebSocketContext);
  if (!ctx) {
    throw new Error(
      "useFactoryWebSocket must be used within a WebSocketProvider"
    );
  }
  return ctx;
}
