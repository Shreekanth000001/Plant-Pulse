"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
} from "react";
import { getWsUrl, fetchQueueDepths, fetchLatestMachines } from "../lib/api";
import {
  WebSocketMessage,
  QCResultPayload,
  QueueHandoffs,
  BackendQueueDepths,
  mapBackendQueueDepths,
  MachineStatus,
  KNOWN_MACHINES,
  isTelemetryMessage,
  Readings,
  isReadingValue,
} from "../types/factory";

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

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
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

const MAX_RECONNECT_DELAY_MS = 15000;
const INITIAL_RECONNECT_DELAY_MS = 1500;

function createDefaultMachines(): Record<string, MachineStatus> {
  const initial: Record<string, MachineStatus> = {};
  for (const [id, meta] of Object.entries(KNOWN_MACHINES)) {
    initial[id] = {
      machine_id: id,
      name: meta.name,
      sub_facility: meta.stage,
      machine_state: "IDLE",
      phase: "IDLE",
      starved: false,
      good_count: 0,
      reject_count: 0,
      extra: {},
    };
  }
  return initial;
}

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const [lastMessageAt, setLastMessageAt] = useState<string | null>(null);
  const [recentQcResults, setRecentQcResults] = useState<QCNotification[]>([]);
  const [handoffs, setHandoffs] = useState<QueueHandoffs>({
    housingToCasting: 0,
    castingToAssembly: 0,
    assemblyToQc: 0,
  });
  const [machines, setMachines] = useState<Record<string, MachineStatus>>(
    createDefaultMachines
  );

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY_MS);
  const isCleanedUpRef = useRef(false);
  const subscribersRef = useRef<Set<(message: WebSocketMessage) => void>>(
    new Set()
  );

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

  const connect = useCallback(function tryConnect() {
    if (typeof window === "undefined") return;

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    const wsUrl = getWsUrl();
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("connected");
        setReconnectAttempt(0);
        reconnectDelayRef.current = INITIAL_RECONNECT_DELAY_MS;

        // Refresh queue depths & machines on connection
        fetchQueueDepths()
          .then((depths) => {
            setHandoffs(mapBackendQueueDepths(depths));
          })
          .catch((err) => {
            console.warn("Failed to refresh queue depths on connect:", err);
          });

        fetchLatestMachines()
          .then((data) => {
            setMachines((prev) => {
              const updated = { ...prev };
              for (const m of data) {
                updated[m.machine_id] = m;
              }
              return updated;
            });
          })
          .catch((err) => {
            console.warn("Failed to refresh machines on connect:", err);
          });
      };

      ws.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data) as WebSocketMessage;
          setLastMessageAt(new Date().toISOString());

          // Dispatch to all subscribers
          subscribersRef.current.forEach((cb) => {
            try {
              cb(raw);
            } catch (err) {
              console.error("Error in telemetry subscriber callback:", err);
            }
          });

          const topic = raw.topic || "";

          // Real backend queue depths topic
          if (topic === "factory/queue_depths") {
            const depths = raw.payload as BackendQueueDepths;
            setHandoffs(mapBackendQueueDepths(depths));
          } else if (isTelemetryMessage(raw)) {
            const parts = topic.split("/");
            if (parts.length >= 4) {
              const subFacility = parts[1];
              const machineId = parts[2];
              const payload = raw.payload || {};

              setMachines((prev) => {
                const existing = prev[machineId] || {
                  machine_id: machineId,
                  sub_facility: subFacility,
                  name: KNOWN_MACHINES[machineId]?.name || machineId,
                  machine_state: "IDLE",
                  starved: false,
                  extra: {},
                };

                const excluded = new Set([
                  "machine_id",
                  "name",
                  "machine_state",
                  "phase",
                  "starved",
                  "current_unit",
                  "current_unit_id",
                  "vibration",
                  "vibration_wear_level",
                  "good_count",
                  "reject_count",
                  "stage_event",
                  "last_result",
                ]);

                const mergedExtra: Readings = {
                  ...(existing.extra || {}),
                };

                for (const [key, value] of Object.entries(payload)) {
                  if (!excluded.has(key) && isReadingValue(value)) {
                    mergedExtra[key] = value;
                  }
                }

                const currentUnit =
                  payload.current_unit !== undefined
                    ? payload.current_unit
                    : payload.current_unit_id !== undefined
                    ? payload.current_unit_id
                    : existing.current_unit_id;

                return {
                  ...prev,
                  [machineId]: {
                    ...existing,
                    machine_id: machineId,
                    sub_facility: subFacility,
                    name: payload.name || existing.name,
                    machine_state:
                      payload.machine_state || existing.machine_state || "IDLE",
                    phase:
                      payload.phase !== undefined
                        ? payload.phase
                        : existing.phase,
                    starved:
                      payload.starved !== undefined
                        ? Boolean(payload.starved)
                        : existing.starved,
                    current_unit_id: currentUnit,
                    vibration:
                      payload.vibration !== undefined
                        ? payload.vibration
                        : existing.vibration,
                    vibration_wear_level:
                      payload.vibration_wear_level !== undefined
                        ? payload.vibration_wear_level
                        : existing.vibration_wear_level,
                    good_count:
                      payload.good_count !== undefined
                        ? payload.good_count
                        : existing.good_count,
                    reject_count:
                      payload.reject_count !== undefined
                        ? payload.reject_count
                        : existing.reject_count,
                    extra: mergedExtra,
                    timestamp: new Date().toISOString(),
                  },
                };
              });
            }
          } else if (topic.endsWith("/result")) {
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
              // Deduplicate: avoid duplicate active toasts for the same unit
              if (prev.some((item) => item.unit_id === qcPayload.unit_id)) {
                return prev;
              }
              return [newNotification, ...prev.slice(0, 4)];
            });
          }
        } catch (e) {
          console.warn("Failed to parse incoming WebSocket message:", e);
        }
      };

      ws.onerror = () => {};

      ws.onclose = () => {
        // Do not attempt to reconnect if socket was intentionally closed during component unmount
        if (isCleanedUpRef.current) return;

        setStatus("reconnecting");
        setReconnectAttempt((prev) => prev + 1);

        const delay = reconnectDelayRef.current;
        reconnectDelayRef.current = Math.min(
          reconnectDelayRef.current * 1.5,
          MAX_RECONNECT_DELAY_MS
        );

        reconnectTimeoutRef.current = setTimeout(() => {
          if (!isCleanedUpRef.current) {
            tryConnect();
          }
        }, delay);
      };
    } catch {
      setStatus("disconnected");
    }
  }, []);

  // Initial load
  useEffect(() => {
    let isMounted = true;
    async function loadInitial() {
      try {
        const [depths, latest] = await Promise.all([
          fetchQueueDepths().catch(() => null),
          fetchLatestMachines().catch(() => []),
        ]);
        if (!isMounted) return;
        if (depths) {
          setHandoffs(mapBackendQueueDepths(depths));
        }
        if (latest && latest.length > 0) {
          setMachines((prev) => {
            const updated = { ...prev };
            for (const m of latest) {
              updated[m.machine_id] = m;
            }
            return updated;
          });
        }
      } catch (err) {
        console.warn("Failed to fetch initial state:", err);
      }
    }

    loadInitial();
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    isCleanedUpRef.current = false;
    connect();

    return () => {
      isCleanedUpRef.current = true;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return (
    <WebSocketContext.Provider
      value={{
        status,
        reconnectAttempt,
        lastMessageAt,
        handoffs,
        machines,
        recentQcResults,
        dismissNotification,
        subscribeToTelemetry,
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
