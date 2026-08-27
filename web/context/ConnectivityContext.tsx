"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

/**
 * Connectivity states for the AI Guru application.
 *
 * - ONLINE: Full connectivity to backend and internet
 * - OFFLINE: No network connectivity
 * - LIMITED: Backend reachable but internet unavailable (local Ollama mode)
 * - RECONNECTING: Attempting to re-establish connection
 */
export type ConnectivityState =
  | "ONLINE"
  | "OFFLINE"
  | "LIMITED"
  | "RECONNECTING";

interface ConnectivityContextValue {
  /** Current connectivity state */
  state: ConnectivityState;
  /** Whether the backend API is reachable */
  backendReachable: boolean;
  /** Whether external internet is available */
  internetAvailable: boolean;
  /** Timestamp of last successful health check */
  lastCheckAt: number | null;
  /** Force a connectivity re-check */
  forceCheck: () => Promise<void>;
}

const ConnectivityContext = createContext<ConnectivityContextValue>({
  state: "ONLINE",
  backendReachable: true,
  internetAvailable: true,
  lastCheckAt: null,
  forceCheck: async () => {},
});

/** Health check interval in milliseconds (30s) */
const HEALTH_CHECK_INTERVAL = 30_000;
/** Reconnection attempt interval (5s) */
const RECONNECT_INTERVAL = 5_000;

/**
 * ConnectivityProvider monitors network state via:
 * 1. `navigator.onLine` + window online/offline events
 * 2. Periodic heartbeat to `/api/v1/health` backend endpoint
 *
 * Automatically transitions between ONLINE/OFFLINE/LIMITED/RECONNECTING.
 */
export function ConnectivityProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<ConnectivityState>("ONLINE");
  const [backendReachable, setBackendReachable] = useState(true);
  const [internetAvailable, setInternetAvailable] = useState(true);
  const [lastCheckAt, setLastCheckAt] = useState<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const checkHealth = useCallback(async () => {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 5000);

      const res = await fetch("/api/v1/health", {
        signal: controller.signal,
        cache: "no-store",
      });
      clearTimeout(timeout);

      const isBackendOk = res.ok;
      const isOnline = navigator.onLine;

      setBackendReachable(isBackendOk);
      setInternetAvailable(isOnline);
      setLastCheckAt(Date.now());

      if (isBackendOk && isOnline) {
        setState("ONLINE");
        // Clear reconnection timer if running
        if (reconnectRef.current) {
          clearInterval(reconnectRef.current);
          reconnectRef.current = null;
        }
      } else if (isBackendOk && !isOnline) {
        setState("LIMITED");
      } else {
        setState("OFFLINE");
      }
    } catch {
      // Backend unreachable
      setBackendReachable(false);
      setLastCheckAt(Date.now());

      if (!navigator.onLine) {
        setInternetAvailable(false);
        setState("OFFLINE");
      } else {
        setState("RECONNECTING");
        // Start reconnection attempts
        if (!reconnectRef.current) {
          reconnectRef.current = setInterval(async () => {
            try {
              const res = await fetch("/api/v1/health", {
                cache: "no-store",
              });
              if (res.ok) {
                setBackendReachable(true);
                setState(navigator.onLine ? "ONLINE" : "LIMITED");
                if (reconnectRef.current) {
                  clearInterval(reconnectRef.current);
                  reconnectRef.current = null;
                }
              }
            } catch {
              // Still reconnecting
            }
          }, RECONNECT_INTERVAL);
        }
      }
    }
  }, []);

  const forceCheck = useCallback(async () => {
    await checkHealth();
  }, [checkHealth]);

  // Initial check + periodic heartbeat
  useEffect(() => {
    const timer = setTimeout(() => {
      void checkHealth();
    }, 0);
    intervalRef.current = setInterval(checkHealth, HEALTH_CHECK_INTERVAL);
    return () => {
      clearTimeout(timer);
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (reconnectRef.current) clearInterval(reconnectRef.current);
    };
  }, [checkHealth]);

  // Listen for browser online/offline events
  useEffect(() => {
    const handleOnline = () => {
      setInternetAvailable(true);
      void checkHealth();
    };
    const handleOffline = () => {
      setInternetAvailable(false);
      setState("OFFLINE");
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [checkHealth]);

  return (
    <ConnectivityContext.Provider
      value={{ state, backendReachable, internetAvailable, lastCheckAt, forceCheck }}
    >
      {children}
    </ConnectivityContext.Provider>
  );
}

/**
 * Hook to access the current connectivity state.
 *
 * @example
 * ```tsx
 * const { state, forceCheck } = useConnectivity();
 * if (state === 'OFFLINE') showOfflineBanner();
 * ```
 */
export function useConnectivity() {
  return useContext(ConnectivityContext);
}
