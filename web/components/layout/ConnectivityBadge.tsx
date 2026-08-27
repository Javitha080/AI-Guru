"use client";

import { useConnectivity, type ConnectivityState } from "@/context/ConnectivityContext";
import {
  Cloud,
  CloudOff,
  Loader2,
  WifiOff,
} from "lucide-react";

/**
 * Mapping of connectivity states to UI configuration.
 */
const STATE_CONFIG: Record<
  ConnectivityState,
  { icon: typeof Cloud; label: string; color: string; pulse: boolean }
> = {
  ONLINE: {
    icon: Cloud,
    label: "Online",
    color: "text-emerald-500",
    pulse: false,
  },
  OFFLINE: {
    icon: CloudOff,
    label: "Offline",
    color: "text-red-500",
    pulse: false,
  },
  LIMITED: {
    icon: WifiOff,
    label: "Limited",
    color: "text-amber-500",
    pulse: false,
  },
  RECONNECTING: {
    icon: Loader2,
    label: "Reconnecting…",
    color: "text-amber-500",
    pulse: true,
  },
};

/**
 * A compact connectivity status badge for the navbar/header.
 *
 * Shows a color-coded icon and label reflecting the current connectivity state.
 * When ONLINE it remains subtle; other states are visually prominent.
 *
 * @example
 * ```tsx
 * <ConnectivityBadge />
 * ```
 */
export function ConnectivityBadge() {
  const { state, forceCheck } = useConnectivity();
  const config = STATE_CONFIG[state];
  const Icon = config.icon;

  // When online, show a minimal indicator that doesn't distract
  if (state === "ONLINE") {
    return null;
  }

  return (
    <button
      type="button"
      onClick={() => void forceCheck()}
      title={`Connection: ${config.label}. Click to retry.`}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-all duration-150 hover:scale-105 active:scale-95 ${config.color} bg-[var(--background)]/80 border border-[var(--border)]/50 hover:bg-[var(--accent)]/50`}
    >
      <Icon
        size={12}
        strokeWidth={2}
        className={config.pulse ? "animate-spin" : ""}
      />
      <span>{config.label}</span>
    </button>
  );
}
