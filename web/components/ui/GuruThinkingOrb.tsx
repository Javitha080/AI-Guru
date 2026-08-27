"use client";

import React, { useSyncExternalStore } from "react";
import { ThinkingOrb, type OrbState, type OrbSize, type OrbTheme } from "thinking-orbs";

const emptySubscribe = () => () => {};
const useMounted = () => useSyncExternalStore(emptySubscribe, () => true, () => false);

export type GuruOrbState = OrbState;
export type GuruOrbSize = OrbSize | number;

export interface GuruThinkingOrbProps {
  /** The animated state of the thought orb. */
  state?: GuruOrbState;
  /** Size preset (64 for cards/hero, 20 for inline/compact) or custom CSS size. */
  size?: GuruOrbSize;
  /** Animation speed multiplier. Default 1. */
  speed?: number;
  /** Palette theme mode. Default 'auto'. */
  theme?: OrbTheme;
  /** Freeze animation on current frame. */
  paused?: boolean;
  /** Visual presentation variant. */
  variant?: "pill" | "card" | "inline" | "orb-only";
  /** Optional custom text label. Defaults to preset label for the state. */
  label?: string;
  /** Enable Transitions.dev text shimmer on the label. Default true. */
  shimmer?: boolean;
  /** Additional custom container classes. */
  className?: string;
  /** Additional custom pill classes (for pill / card variants). */
  pillClassName?: string;
  /** Suffix / children e.g. duration badge or action button. */
  children?: React.ReactNode;
}

const DEFAULT_LABELS: Record<GuruOrbState, string> = {
  solving: "Solving....",
  breathing: "Thinking....",
  listening: "Agent listening...",
  working: "Working....",
  searching: "Searching....",
  connecting: "Connecting....",
  weaving: "Weaving....",
  composing: "Composing....",
  shaping: "Shaping....",
};

/**
 * Maps AI Guru streaming modes & capabilities to Thinking Orb states.
 */
export function mapAgentModeToOrb(mode: string, agentName = "AI Guru"): {
  state: GuruOrbState;
  label: string;
} {
  const normalized = (mode || "").toLowerCase().trim();

  switch (normalized) {
    case "solving":
    case "deep_solve":
    case "math":
      return { state: "solving", label: `${agentName} Solving…` };

    case "searching":
    case "exploring":
    case "deep_research":
    case "rag":
    case "web_search":
      return { state: "searching", label: `${agentName} Searching…` };

    case "listening":
    case "voice":
    case "vision":
    case "monitoring":
      return { state: "listening", label: "Agent listening…" };

    case "tool_using":
    case "tool_call":
    case "code_execution":
      return { state: "working", label: "Tool Working…" };

    case "connecting":
    case "subagent":
    case "mcp":
      return { state: "connecting", label: "Connecting Agents…" };

    case "drafting":
    case "writing":
    case "responding":
    case "co_writer":
      return { state: "composing", label: `${agentName} Composing…` };

    case "planning":
    case "decompose":
      return { state: "shaping", label: `${agentName} Planning…` };

    case "reflecting":
    case "quizzing":
      return { state: "weaving", label: `${agentName} Reflecting…` };

    case "reasoning":
    case "thinking":
    default:
      return { state: "breathing", label: `${agentName} Thinking…` };
  }
}

/**
 * AI Guru Thinking Orb Component
 * Supports Jakub Antalik's Thinking Orbs with Transitions.dev text shimmering
 * and the dark capsule pill / card design from the reference image.
 */
export default function GuruThinkingOrb({
  state = "working",
  size = 64,
  speed = 1,
  theme = "auto",
  paused = false,
  variant = "pill",
  label,
  shimmer = true,
  className = "",
  pillClassName = "",
  children,
}: GuruThinkingOrbProps) {
  const mounted = useMounted();

  const displayLabel = label ?? DEFAULT_LABELS[state] ?? "Thinking…";
  const canvasSize: OrbSize = size === 20 ? 20 : 64;

  const orbElement = mounted ? (
    <ThinkingOrb
      state={state}
      size={canvasSize}
      speed={speed}
      theme={theme}
      paused={paused}
      aria-label={displayLabel}
    />
  ) : (
    <div
      style={{ width: `${canvasSize}px`, height: `${canvasSize}px` }}
      className="flex items-center justify-center rounded-full bg-white/5 opacity-50"
    />
  );

  // Variant: Raw Orb Only
  if (variant === "orb-only") {
    return (
      <div className={`inline-flex items-center justify-center ${className}`}>
        {orbElement}
      </div>
    );
  }

  // Text label with Transitions.dev shimmer
  const labelElement = shimmer ? (
    <span className="t-think text-left" role="status">
      <span className="t-think-sizer" aria-hidden="true">
        {displayLabel}
      </span>
      <span className="t-think-text text-zinc-200" data-text={displayLabel}>
        {displayLabel}
      </span>
    </span>
  ) : (
    <span className="text-zinc-200">{displayLabel}</span>
  );

  // Variant: Inline indicator (compact for headers, trace lines, breadcrumbs)
  if (variant === "inline") {
    return (
      <div
        className={`inline-flex items-center gap-2 text-xs font-medium text-zinc-300 ${className}`}
      >
        <div className="shrink-0 flex items-center justify-center" style={{ width: 20, height: 20 }}>
          {orbElement}
        </div>
        {labelElement}
        {children}
      </div>
    );
  }

  // Capsule Pill badge (matching reference image)
  const pillContent = (
    <div
      className={`group flex items-center gap-3 rounded-full border border-zinc-800/80 bg-[#18181b]/90 px-4 py-2 text-sm font-medium text-zinc-200 shadow-xl shadow-black/40 backdrop-blur-md transition-all duration-300 hover:border-zinc-700/80 hover:bg-[#202024]/95 ${
        canvasSize === 20 ? "py-1.5 px-3 text-xs" : ""
      } ${pillClassName}`}
    >
      <div className="shrink-0 flex items-center justify-center">
        {orbElement}
      </div>
      <div className="flex items-center gap-2">
        {labelElement}
        {children}
      </div>
    </div>
  );

  // Variant: Card container (exact 2x2 showcase style from user image)
  if (variant === "card") {
    return (
      <div
        className={`relative flex min-h-[220px] w-full items-center justify-center rounded-3xl border border-white/[0.06] bg-[#121316] p-8 shadow-2xl transition-all duration-300 hover:border-white/[0.12] hover:bg-[#15161a] ${className}`}
      >
        {pillContent}
      </div>
    );
  }

  // Default: Pill Capsule
  return (
    <div className={`inline-flex items-center ${className}`}>
      {pillContent}
    </div>
  );
}
