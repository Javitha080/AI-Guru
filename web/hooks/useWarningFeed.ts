"use client";

import { useState, useCallback } from "react";
import { notify } from "@/lib/notifications";
import { useStudyAudio, type ChimeSeverity } from "./useStudyAudio";

export interface LiveWarning {
  warning_id: string;
  category: string;
  message: string;
  severity: string;
  at: number;
}

/** Live warning feed: dedupes by id, chimes, toasts, and tracks Telegram badge. */
export function useWarningFeed() {
  const { playChime } = useStudyAudio();
  const [liveWarnings, setLiveWarnings] = useState<LiveWarning[]>([]);
  const [telegramBadgeAt, setTelegramBadgeAt] = useState<number | null>(null);

  const pushWarning = useCallback(
    (warn: { warning_id?: string; category?: string; message?: string; severity?: string } | undefined) => {
      if (!warn?.warning_id) return;
      setLiveWarnings((prev) =>
        [{ ...warn, at: Date.now() } as LiveWarning, ...prev.filter((w) => w.warning_id !== warn.warning_id)].slice(0, 5)
      );
      if (warn.severity === "alert") setTelegramBadgeAt(Date.now());
      const sev: ChimeSeverity =
        warn.severity === "alert" || warn.severity === "warning" || warn.severity === "nudge" ? warn.severity : "nudge";
      playChime(sev);
      notify(warn.message || "Stay focused!", {
        tone: warn.severity === "alert" ? "error" : warn.severity === "warning" ? "warning" : "info",
      });
    },
    [playChime]
  );

  const reset = useCallback(() => {
    setLiveWarnings([]);
    setTelegramBadgeAt(null);
  }, []);

  const telegramBadgeVisible = telegramBadgeAt !== null && Date.now() - telegramBadgeAt < 8000;

  return { liveWarnings, pushWarning, reset, telegramBadgeAt, setTelegramBadgeAt, telegramBadgeVisible };
}
