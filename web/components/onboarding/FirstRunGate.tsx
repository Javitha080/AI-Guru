"use client";

/**
 * First-run gate: mounts the AIWizard onboarding overlay when the user has
 * never completed it AND no LLM provider is configured yet. Dismissal
 * persists to localStorage so returning users are never nagged.
 */

import React, { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { apiFetch, apiUrl } from "@/lib/api";

const AIWizard = dynamic(
  () => import("@/components/onboarding/AIWizard").then((m) => ({ default: m.AIWizard })),
  { ssr: false },
);

const FLAG_KEY = "aiguru.onboarded";

export default function FirstRunGate() {
  const [show, setShow] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        if (window.localStorage.getItem(FLAG_KEY) === "1") return;
        const res = await apiFetch(apiUrl("/api/v1/ai-provider/status"));
        if (!res.ok || cancelled) return;
        const status = await res.json().catch(() => null);
        // Only nag when nothing is usable yet.
        const configured =
          status?.llm?.available ||
          status?.ollama?.available ||
          status?.offline?.available ||
          Boolean(status?.api_key_configured) ||
          Boolean(status?.configured);
        if (!configured) setShow(true);
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
            onClose={() => {
              try {
                window.localStorage.setItem(FLAG_KEY, "1");
              } catch {
                /* ignore */
              }
              setShow(false);
            }}
            onComplete={() => {
              try {
                window.localStorage.setItem(FLAG_KEY, "1");
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
