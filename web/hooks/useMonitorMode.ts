"use client";

import { useState, useEffect } from "react";
import { monitoringApi } from "@/lib/monitoring/monitoringApi";

export type MonitorMode = "system" | "browser";

/** Probe once per active session: system camera vs browser WASM fallback. */
export function useMonitorMode(isActive: boolean, sessionId: string | null) {
  const [monitorMode, setMonitorMode] = useState<MonitorMode | null>(null);

  useEffect(() => {
    if (!isActive || monitorMode !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(monitoringApi.cameraStatus);
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (!cancelled) {
          setMonitorMode(data.mode === "system" && sessionId ? "system" : "browser");
        }
      } catch {
        if (!cancelled) setMonitorMode("browser");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isActive, sessionId, monitorMode]);

  return { monitorMode, setMonitorMode };
}
