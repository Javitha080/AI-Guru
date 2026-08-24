"use client";

/**
 * First-run gate: mounts the AIWizard onboarding overlay when the user has
 * never completed setup AND no usable LLM provider is configured yet.
 *
 * Dismissal semantics are deliberately asymmetric:
 * - Completing setup with a verified provider persists `aiguru.onboarded`
 *   to localStorage → never nagged again.
 * - Closing early ("Skip for now") persists nothing global; the prompt is
 *   suppressed for this browser session only, so the next launch nags again
 *   until setup actually succeeded.
 */

import React, { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { apiFetch, apiUrl } from "@/lib/api";

const AIWizard = dynamic(
  () => import("@/components/onboarding/AIWizard").then((m) => ({ default: m.AIWizard })),
  { ssr: false },
);

const FLAG_KEY = "aiguru.onboarded";
const SESSION_SUPPRESS_KEY = "aiguru.onboarding.suppressed-session";

interface ProviderStatus {
  mode?: string;
  persisted_tutoring_mode?: string | null;
  configured?: boolean;
  cloud?: { health?: { available?: boolean } };
  ollama?: { health?: { available?: boolean } };
  offline?: { health?: { available?: boolean } };
}

export default function FirstRunGate() {
  const [show, setShow] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        if (window.localStorage.getItem(FLAG_KEY) === "1") return;
        if (window.sessionStorage.getItem(SESSION_SUPPRESS_KEY) === "1") return;
        const res = await apiFetch(apiUrl("/api/v1/ai-provider/status"));
        if (!res.ok || cancelled) return;
        const status: ProviderStatus | null = await res.json().catch(() => null);
        if (!status) return;
        // Only nag when nothing is usable yet. `configured` is computed
        // server-side from the same resolver the tutor pipeline uses; the
        // health blocks cover local Ollama / explicit offline setups.
        const offlineChosen = status.persisted_tutoring_mode === "offline";
        const hasLocalOllama = Boolean(status.ollama?.health?.available);
        const configured =
          Boolean(status.configured) ||
          Boolean(status.cloud?.health?.available) ||
          Boolean(status.offline?.health?.available) ||
          hasLocalOllama ||
          offlineChosen;
        if (!configured && !cancelled) setShow(true);
      } catch {
        /* backend unreachable — don't block the app with a wizard */
      } finally {
        if (!cancelled) setChecked(true);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!checked || !show) return null;

  return (
    <div className="fixed inset-0 z-[10000] overflow-auto bg-black/70 backdrop-blur-sm">
      <div className="min-h-full flex items-center justify-center p-4">
        <div className="w-full max-w-2xl">
          <AIWizard
            isOpen
            onComplete={() => {
              // Only a verified completion clears the gate for good.
              try {
                window.localStorage.setItem(FLAG_KEY, "1");
                window.sessionStorage.removeItem(SESSION_SUPPRESS_KEY);
              } catch {
                /* ignore */
              }
              setShow(false);
            }}
            onClose={() => {
              // Early dismissal: suppress for THIS session only.
              try {
                window.sessionStorage.setItem(SESSION_SUPPRESS_KEY, "1");
              } catch {
                /* ignore */
              }
              setShow(false);
            }}
          />
        </div>
      </div>
    </div>
  );
}
