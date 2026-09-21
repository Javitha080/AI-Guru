"use client";

import React from "react";
import { Mic, MicOff, PhoneCall, Volume2 } from "lucide-react";

interface VoiceDropInBannerProps {
  secondsLeft: number;
  micMuted: boolean;
  volume: number;
  announcement: string | null;
  onToggleMute: (muted: boolean) => void;
  onVolume: (v: number) => void;
}

function formatLeft(secs: number): string {
  const s = Math.max(0, Math.round(secs));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function VoiceDropInBanner({
  secondsLeft,
  micMuted,
  volume,
  announcement,
  onToggleMute,
  onVolume,
}: VoiceDropInBannerProps) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="mx-3 mt-2 rounded-2xl px-4 py-3 flex flex-wrap items-center gap-3 border border-[var(--ember-line)]/50 bg-gradient-to-r from-[var(--ember-0)] to-[var(--amber-glow)]/40 shadow-[0_0_22px_var(--glow-primary)] relative z-30"
    >
      <span className="flex items-center gap-2 text-sm font-bold text-[var(--primary)]">
        <span className="w-2 h-2 rounded-full bg-[var(--primary)] ember-dot" />
        <PhoneCall size={16} />
        Parent talking… {formatLeft(secondsLeft)} left
      </span>
      <span className="text-[11px] text-[var(--muted-foreground)]">
        Auto-answers during study · ends automatically · no action needed
      </span>
      <div className="ml-auto flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-[11px] font-semibold text-[var(--muted-foreground)]">
          <Volume2 size={14} />
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={volume}
            onChange={(e) => onVolume(Number(e.target.value))}
            aria-label="Parent voice volume"
            className="w-24 accent-[var(--primary)]"
          />
        </label>
        <button
          onClick={() => onToggleMute(!micMuted)}
          aria-pressed={micMuted}
          title={micMuted ? "Unmute my mic" : "Mute my mic"}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border transition-colors ${
            micMuted
              ? "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--glass-border)]"
              : "bg-[var(--ember-0)] text-[var(--primary)] border-[var(--ember-line)]/40"
          }`}
        >
          {micMuted ? <MicOff size={14} /> : <Mic size={14} />}
          <span>{micMuted ? "Mic off" : "Mic on"}</span>
        </button>
      </div>
      {announcement && (
        <p className="w-full text-xs text-[var(--foreground)] bg-black/20 border border-[var(--glass-border)] rounded-xl px-3 py-2">
          {announcement}
        </p>
      )}
    </div>
  );
}
