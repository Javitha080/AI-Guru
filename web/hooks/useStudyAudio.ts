"use client";

import { useRef, useCallback } from "react";

export type ChimeSeverity = "nudge" | "warning" | "alert";

/**
 * Lightweight Web Audio chime for distraction warnings — no external files.
 * Uses lazy AudioContext initialization and respects autoplay policy.
 */
export function useStudyAudio() {
  const audioCtxRef = useRef<AudioContext | null>(null);

  const getAudioContext = useCallback(() => {
    if (typeof AudioContext === "undefined") return null;
    if (!audioCtxRef.current) {
      audioCtxRef.current = new AudioContext();
    }
    return audioCtxRef.current;
  }, []);

  const playChime = useCallback((severity: ChimeSeverity): void => {
    const ctx = getAudioContext();
    if (!ctx) return;
    try {
      // Resume context on user interaction (Chrome autoplay policy)
      if (ctx.state === "suspended") {
        void ctx.resume();
      }
      const t = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = severity === "alert" ? "triangle" : "sine";

      // Nudge: gentle rising double-ping; Warning/Alert: descending attention tone
      if (severity === "nudge") {
        osc.frequency.setValueAtTime(523, t); // C5
        osc.frequency.setValueAtTime(659, t + 0.12); // E5
        gain.gain.setValueAtTime(0.08, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
        osc.start(t);
        osc.stop(t + 0.3);
      } else {
        const vol = severity === "alert" ? 0.15 : 0.1;
        osc.frequency.setValueAtTime(880, t); // A5
        osc.frequency.setValueAtTime(659, t + 0.08); // E5
        osc.frequency.setValueAtTime(523, t + 0.16); // C5
        gain.gain.setValueAtTime(vol, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.4);
        osc.start(t);
        osc.stop(t + 0.4);
      }
    } catch {
      /* audio unavailable — silent fallback */
    }
  }, [getAudioContext]);

  return { playChime };
}
