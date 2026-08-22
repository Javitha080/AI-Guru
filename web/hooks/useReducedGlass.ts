"use client";

import { useEffect, useState, useCallback } from "react";

const GLASS_PREF_KEY = "aiguru.glass-effects";

/**
 * Detects whether glass effects (backdrop-filter: blur) should be active.
 *
 * Returns `shouldUseGlass = true` when:
 *   • The user hasn't set `prefers-reduced-transparency: reduce`
 *   • AND the manual "reduce glass effects" setting isn't stored as `"off"`.
 *
 * Components use this to swap glass surfaces for opaque fallbacks, e.g.
 *   className={shouldUseGlass ? "surface-glass-elevated" : "surface-card"}
 */
export function useReducedGlass() {
  const [shouldUseGlass, setShouldUseGlass] = useState(true);

  useEffect(() => {
    // Check OS-level preference
    const mq = window.matchMedia("(prefers-reduced-transparency: reduce)");
    const stored = localStorage.getItem(GLASS_PREF_KEY);

    const decide = () => {
      if (stored === "off" || mq.matches) {
        setShouldUseGlass(false);
      } else {
        setShouldUseGlass(true);
      }
    };

    decide();

    const handler = () => decide();
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const setGlassEnabled = useCallback((enabled: boolean) => {
    localStorage.setItem(GLASS_PREF_KEY, enabled ? "on" : "off");
    setShouldUseGlass(enabled);
  }, []);

  return { shouldUseGlass, setGlassEnabled };
}
