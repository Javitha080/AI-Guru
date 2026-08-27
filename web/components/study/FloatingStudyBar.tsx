"use client";

/**
 * Floating study pill — Ember Glass. Mirrors the page clock exactly,
 * hands questions off to the app-wide Floating Guru, pops a Document PiP
 * timer on Chromium. No simulated values: focus shows "—" until real data.
 */

import React, { useState, useRef } from "react";
import {
  Sparkles, X, Send, Play, Pause,
  Clock, ExternalLink, Bot,
} from "lucide-react";
import GuruThinkingOrb from "@/components/ui/GuruThinkingOrb";
import AnimatedNumber from "@/components/ui/AnimatedNumber";

interface FloatingStudyBarProps {
  sessionTitle: string;
  subject: string;
  /** Seconds remaining — single source of truth is the page's clock. */
  timeLeft: number | null;
  isPaused: boolean;
  onTogglePause: () => void;
  /** Null until real telemetry arrives; renders "—" instead of a fake number. */
  focusScore: number | null;
}

export default function FloatingStudyBar({
  sessionTitle,
  subject,
  timeLeft,
  isPaused,
  onTogglePause,
  focusScore,
}: FloatingStudyBarProps) {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [inputQuery, setInputQuery] = useState("");
  // Document Picture-in-Picture handle; the interval below keeps its clock live.
  const pipWindowRef = useRef<Window | null>(null);

  const formatTime = (secs: number | null) => {
    if (secs === null || !Number.isFinite(secs)) return "--:--";
    const total = Math.max(0, Math.floor(secs));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // Keep an open PiP window in sync (timer + focus) instead of writing static
  // HTML once. Cleared automatically when the user closes the PiP window.
  React.useEffect(() => {
    const pip = pipWindowRef.current;
    if (!pip || pip.closed) return;
    const tick = () => {
      if (pip.closed) return;
      try {
        const el = pip.document.getElementById("aiguru-pip-timer");
        if (el) el.textContent = formatTime(timeLeft);
        const f = pip.document.getElementById("aiguru-pip-focus");
        if (f) f.textContent = focusScore === null ? "Focus: —" : `Focus: ${focusScore}%`;
      } catch {
        /* window went away mid-update */
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [timeLeft, focusScore]);

  const handleOpenPiP = async () => {
    if (typeof window !== "undefined" && "documentPictureInPicture" in window) {
      try {
        // Reuse the existing popout instead of stacking duplicates.
        const existing = pipWindowRef.current;
        if (existing && !existing.closed) {
          existing.focus();
          return;
        }
        // @ts-expect-error documentPictureInPicture is Chromium-only
        const pipWindow: Window = await window.documentPictureInPicture.requestWindow({
          width: 340,
          height: 180,
        });
        pipWindowRef.current = pipWindow;
        pipWindow.document.body.innerHTML = `
          <div style="font-family: system-ui, sans-serif; background: #0B0E14; color: #F1F3F7; padding: 16px; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="font-size: 11px; font-weight: bold; color: #F0956A; text-transform: uppercase;">AI GURU • ${subject}</span>
              <span id="aiguru-pip-focus" style="font-size: 11px; background: rgba(224,109,68,0.16); color: #F0B429; padding: 2px 8px; border-radius: 9999px;">${focusScore === null ? "Focus: —" : `Focus: ${focusScore}%`}</span>
            </div>
            <div style="text-align: center; margin: 8px 0;">
              <div id="aiguru-pip-timer" style="font-size: 32px; font-weight: 800; font-family: monospace; letter-spacing: 2px; color: #E06D44;">
                ${formatTime(timeLeft)}
              </div>
              <div style="font-size: 11px; color: #94A3B8;">${sessionTitle}</div>
            </div>
            <div style="font-size: 10px; color: #64748b; text-align: center;">
              &#128293; Local AI Vision Guard Active (0 Cloud Egress)
            </div>
          </div>
        `;
        pipWindow.addEventListener("pagehide", () => {
          pipWindowRef.current = null;
        });
      } catch (err) {
        console.warn("Document PiP unavailable", err);
      }
    }
    // No alert() spam when unsupported — the floating bar itself already works everywhere.
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputQuery.trim()) return;
    // Hand off to the app-wide Floating Guru assistant (unified WS agent loop).
    const question = inputQuery.trim();
    setInputQuery("");
    setIsChatOpen(false);
    window.dispatchEvent(
      new CustomEvent("aiguru:open-floating-chat", {
        detail: { context: `Studying ${subject}. Question: ${question}` },
      })
    );
  };

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3 pointer-events-auto select-none">
      {/* 1. EXPANDABLE FLOATING AI GURU CHAT HANDOFF */}
      {isChatOpen && (
        <div className="bento-cell w-96 max-w-[calc(100vw-32px)] h-[440px] flex flex-col overflow-hidden !rounded-2xl animate-pop-in">
          {/* Chat Header */}
          <div className="p-3.5 bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white flex items-center justify-between relative z-[2]">
            <div className="flex items-center gap-2.5">
              <span className="p-1.5 bg-white/20 rounded-lg backdrop-blur-sm">
                <Bot size={18} />
              </span>
              <div>
                <h4 className="font-bold text-xs">AI Guru Assistant</h4>
                <p className="text-[10px] text-white/80 font-mono">Monitored · {subject}</p>
              </div>
            </div>
            <button
              onClick={() => setIsChatOpen(false)}
              className="p-1.5 hover:bg-white/20 rounded-lg transition-colors"
              aria-label="Close assistant"
            >
              <X size={16} />
            </button>
          </div>

          {/* Chat Body — hand-off hint */}
          <div className="flex-1 p-4 overflow-y-auto text-xs flex flex-col items-center justify-center gap-3 text-center">
            <Sparkles size={24} className="text-[var(--amber)]" />
            <p className="text-[var(--muted-foreground)] leading-relaxed max-w-[85%]">
              Ask anything — hints, derivations, concept explanations. Your question opens in the{" "}
              <span className="font-semibold text-[var(--foreground)]">AI Guru floating assistant</span>, so it
              stays with you across pages.
            </p>
            <button
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent("aiguru:open-floating-chat", {
                    detail: { context: `Studying ${subject}` },
                  })
                )
              }
              className="glass-btn-primary !rounded-xl text-xs"
            >
              Open Assistant
            </button>
          </div>

          {/* Chat Input Bar */}
          <form onSubmit={handleSendMessage} className="p-2.5 border-t border-[var(--glass-border)] flex items-center gap-2">
            <input
              type="text"
              placeholder="Ask a question, request a hint…"
              value={inputQuery}
              onChange={(e) => setInputQuery(e.target.value)}
              className="glass-input flex-1 !py-2 text-xs"
            />
            <button
              type="submit"
              disabled={!inputQuery.trim()}
              aria-label="Send question to AI Guru"
              className="p-2 bg-[var(--primary)] hover:brightness-110 disabled:opacity-40 text-white rounded-xl transition-all shadow-[0_4px_14px_var(--glow-primary)] disabled:shadow-none"
            >
              <Send size={15} />
            </button>
          </form>
        </div>
      )}

      {/* 2. FLOATING TICKING PILL BAR */}
      <div className="surface-glass-elevated rounded-2xl p-2.5 pl-3.5 flex items-center gap-3 transition-colors duration-300 hover:border-[var(--ember-line)]/50 shadow-[var(--glass-shadow-elevated),0_0_20px_rgba(0,0,0,0.35)]">
        {/* Local AI Vision Guard Active Pill */}
        <GuruThinkingOrb
          state="listening"
          label="Agent listening…"
          size={20}
          variant="inline"
          shimmer
          className="hidden sm:inline-flex rounded-full bg-black/40 border border-white/10 px-2.5 py-1 text-[11px]"
        />

        {/* Timer Display — mirrors the page clock exactly */}
        <div className="flex items-center gap-2">
          <Clock size={16} className={isPaused ? "text-[var(--amber)]" : "text-[var(--primary)]"} />
          <span
            className={`font-mono font-extrabold text-base tracking-wider tabular-nums ${
              isPaused ? "text-[var(--amber)]" : ""
            }`}
          >
            <AnimatedNumber value={formatTime(timeLeft)} />
          </span>
        </div>

        {/* Focus Score Pill — honest dash until real telemetry arrives */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[var(--ember-0)] border border-[var(--glass-border)] text-xs font-bold">
          <span
            className={`w-2 h-2 rounded-full ${
              focusScore === null ? "bg-[var(--muted-foreground)]/50" : "bg-[var(--primary)] ember-dot"
            }`}
          />
          <span className={focusScore === null ? "text-[var(--muted-foreground)]" : "text-[var(--primary)]"}>
            {focusScore === null ? "—" : <AnimatedNumber value={`${Math.round(focusScore)}%`} />}
          </span>
        </div>

        {/* Play/Pause Button — same state as the main session controls */}
        <button
          onClick={onTogglePause}
          className="glow-ring p-1.5 rounded-lg surface-glass-base text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-all duration-150 hover:scale-110 active:scale-90"
          title={isPaused ? "Resume Session" : "Pause Session"}
          aria-label={isPaused ? "Resume session" : "Pause session"}
        >
          {isPaused ? <Play size={16} className="text-[var(--amber)]" /> : <Pause size={16} />}
        </button>

        {/* Picture-in-Picture Popout */}
        <button
          onClick={() => void handleOpenPiP()}
          className="glow-ring p-1.5 rounded-lg surface-glass-base text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-all duration-150 hover:scale-110 active:scale-90"
          title="Pop out timer (Chromium)"
          aria-label="Pop out timer"
        >
          <ExternalLink size={16} />
        </button>

        {/* Floating Chat Trigger */}
        <button
          onClick={() => setIsChatOpen(!isChatOpen)}
          aria-expanded={isChatOpen}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-bold text-xs transition-all duration-200 hover:scale-105 active:scale-95 ${
            isChatOpen
              ? "bg-[var(--primary)] text-white shadow-[0_4px_16px_var(--glow-primary)]"
              : "bg-gradient-to-r from-[var(--primary)]/20 to-[var(--amber)]/15 text-[var(--primary)] border border-[var(--ember-line)]/40 hover:border-[var(--ember-line)]"
          }`}
        >
          <Sparkles size={14} className="text-[var(--amber)]" />
          <span>Ask AI</span>
        </button>
      </div>
    </div>
  );
}
