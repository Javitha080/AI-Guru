"use client";

import { useState, useCallback } from "react";
import { monitoringApi } from "@/lib/monitoring/monitoringApi";

interface UseLiveConsentOptions {
  sessionId: string | null;
  onNotice?: (notice: { kind: "error" | "warn"; text: string } | null) => void;
}

export function useLiveConsent({ sessionId, onNotice }: UseLiveConsentOptions) {
  const [liveViewEnabled, setLiveViewEnabled] = useState(false);

  const toggleLiveView = useCallback(
    async (next: boolean) => {
      setLiveViewEnabled(next);
      if (!sessionId) return;
      try {
        const res = await fetch(monitoringApi.liveConsent(sessionId), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: next }),
        });
        if (!res.ok) throw new Error(String(res.status));
      } catch {
        onNotice?.({
          kind: "warn",
          text: "Could not sync Parent Live View consent with the backend — snapshots won't upload.",
        });
        setLiveViewEnabled(!next);
      }
    },
    [sessionId, onNotice]
  );

  return {
    liveViewEnabled,
    setLiveViewEnabled,
    toggleLiveView,
  };
}
