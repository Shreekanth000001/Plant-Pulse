"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
} from "react";
import { getWsUrl, fetchQueueDepths } from "../lib/api";
import {
  WebSocketMessage,
  QCResultPayload,
  QueueHandoffs,
  BackendQueueDepths,
  mapBackendQueueDepths,
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
  recentQcResults: QCNotification[];
  dismissNotification: (id: string) => void;
  subscribeToTelemetry: (
    callback: (message: WebSocketMessage) => void
  ) => () => void;
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

const MAX_RECONNECT_DELAY_MS = 15000;
const INITIAL_RECONNECT_DELAY_MS = 1500;

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

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY_MS);
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

    // Clear any existing reconnect timer
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

        // Refresh queue depths on connection/reconnection
        fetchQueueDepths()
          .then((depths) => {
            setHandoffs(mapBackendQueueDepths(depths));
          })
          .catch((err) => {
            console.warn("Failed to refresh queue depths on connect:", err);
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
          } else if (topic.endsWith("/result")) {
            const qcPayload = raw.payload as QCResultPayload;
            const newNotification: QCNotification = {
              id: `${qcPayload.unit_id}-${Date.now()}`,
              unit_id: qcPayload.unit_id,
              outcome: qcPayload.outcome,
              defect_type: qcPayload.defect_type,
              attributed_stage: qcPayload.attributed_stage,
              probability: qcPayload.probability,
              timestamp: new Date().toLocaleTimeString(),
            };

            setRecentQcResults((prev) => [newNotification, ...prev.slice(0, 4)]);
          }
        } catch (e) {
          console.warn("Failed to parse incoming WebSocket message:", e);
        }
      };

      ws.onerror = () => {
        // ws.onclose will fire right after this to trigger reconnect
      };

      ws.onclose = () => {
        setStatus("reconnecting");
        setReconnectAttempt((prev) => prev + 1);

        const delay = reconnectDelayRef.current;
        reconnectDelayRef.current = Math.min(
          reconnectDelayRef.current * 1.5,
          MAX_RECONNECT_DELAY_MS
        );

        reconnectTimeoutRef.current = setTimeout(() => {
          tryConnect();
        }, delay);
      };
    } catch {
      setStatus("disconnected");
    }
  }, []);

  // On initial load, fetch initial queue depths from GET /api/queue-depths
  useEffect(() => {
    let isMounted = true;
    async function loadInitialQueueDepths() {
      try {
        const depths = await fetchQueueDepths();
        if (isMounted) {
          setHandoffs(mapBackendQueueDepths(depths));
        }
      } catch (err) {
        console.warn("Failed to fetch initial queue depths:", err);
      }
    }

    loadInitialQueueDepths();
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
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
