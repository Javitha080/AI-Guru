"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  Sparkles, MessageSquare, X, Send, Play, Pause, 
  Clock, Flame, ShieldCheck, Minimize2, Maximize2, ExternalLink,
  ChevronUp, ChevronDown, Bot, Move
} from "lucide-react";

interface FloatingStudyBarProps {
  sessionTitle: string;
  subject: string;
  durationMinutes: number;
  focusScore: number;
  onComplete: () => void;
}

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function FloatingStudyBar({
  sessionTitle,
  subject,
  durationMinutes,
  focusScore,
  onComplete,
}: FloatingStudyBarProps) {
  const [secondsRemaining, setSecondsRemaining] = useState(durationMinutes * 60);
  const [isPaused, setIsPaused] = useState(false);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);

  // Chat hand-off: questions open the app-wide Floating Guru assistant.
  const [inputQuery, setInputQuery] = useState("");

  // Position state for dragging
  const [position, setPosition] = useState<{ x: number; y: number }>({ x: 24, y: 24 });
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startY: number; initX: number; initY: number } | null>(null);

  // Timer interval
  useEffect(() => {
    if (isPaused || secondsRemaining <= 0) return;
    const interval = setInterval(() => {
      setSecondsRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          onComplete();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [isPaused, secondsRemaining, onComplete]);

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // Picture-in-Picture Popout window
  const handleOpenPiP = async () => {
    if (typeof window !== "undefined" && "documentPictureInPicture" in window) {
      try {
        // @ts-ignore
        const pipWindow = await window.documentPictureInPicture.requestWindow({
          width: 340,
          height: 180,
        });

        pipWindow.document.body.innerHTML = `
          <div style="font-family: system-ui, sans-serif; background: #0f172a; color: white; padding: 16px; border-radius: 12px; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="font-size: 11px; font-weight: bold; color: #38bdf8; text-transform: uppercase;">AI GURU • ${subject}</span>
              <span style="font-size: 11px; background: rgba(34, 197, 94, 0.2); color: #4ade80; padding: 2px 8px; border-radius: 9999px;">Focus: ${Math.round(focusScore)}%</span>
            </div>
            <div style="text-align: center; margin: 8px 0;">
              <div style="font-size: 32px; font-weight: 800; font-family: monospace; letter-spacing: 2px;">
                ${formatTime(secondsRemaining)}
              </div>
              <div style="font-size: 11px; color: #94a3b8;">${sessionTitle}</div>
            </div>
            <div style="font-size: 10px; color: #64748b; text-align: center;">
              🛡️ Local AI Vision Guard Active (0 Cloud Egress)
            </div>
          </div>
        `;
      } catch (err) {
        console.log("Document PiP not supported or rejected", err);
      }
    } else {
      alert("Document Picture-in-Picture is active in supported Chromium browsers! You can also keep this floating bar on screen.");
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputQuery.trim()) return;
    // Hand off to the app-wide Floating Guru assistant (unified WS agent loop).
    const question = inputQuery.trim();
    setInputQuery("");
    window.dispatchEvent(
      new CustomEvent("aiguru:open-floating-chat", {
        detail: { context: `Studying ${subject}. Question: ${question}` },
      })
    );
  };

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3 pointer-events-auto select-none">
      {/* 1. EXPANDABLE FLOATING AI GURU CHAT (LIKE CLUELY) */}
      {isChatOpen && (
        <div className="w-96 max-w-[calc(100vw-32px)] h-[440px] bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 flex flex-col overflow-hidden animate-in slide-in-from-bottom-4 duration-200">
          {/* Chat Header */}
          <div className="p-3.5 bg-gradient-to-r from-blue-600 to-indigo-600 text-white flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 bg-white/20 rounded-lg">
                <Bot size={18} />
              </div>
              <div>
                <h4 className="font-bold text-xs">AI Guru Assistant</h4>
                <p className="text-[10px] text-blue-100 font-mono">Monitored • {subject}</p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setIsChatOpen(false)}
                className="p-1.5 hover:bg-white/20 rounded-lg transition-colors"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Chat Body — hand-off hint */}
          <div className="flex-1 p-4 overflow-y-auto bg-gray-50/50 dark:bg-gray-900/50 text-xs flex flex-col items-center justify-center gap-3 text-center">
            <Sparkles size={22} className="text-blue-500" />
            <p className="text-gray-600 dark:text-gray-300 leading-relaxed max-w-[85%]">
              Ask anything — hints, derivations, concept explanations. Your question opens in the{" "}
              <span className="font-semibold">AI Guru floating assistant</span>, so it stays with you across pages.
            </p>
            <button
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent("aiguru:open-floating-chat", {
                    detail: { context: `Studying ${subject}` },
                  })
                )
              }
              className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold transition-colors"
            >
              Open Assistant
            </button>
          </div>

          {/* Chat Input Bar */}
          <form
            onSubmit={handleSendMessage}
            className="p-2.5 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 flex items-center gap-2"
          >
            <input
              type="text"
              placeholder="Ask a question, request a hint, or paste math..."
              value={inputQuery}
              onChange={(e) => setInputQuery(e.target.value)}
              className="flex-1 px-3 py-2 bg-gray-100 dark:bg-gray-700 border-0 rounded-xl text-xs text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={!inputQuery.trim()}
              className="p-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white rounded-xl transition-colors"
            >
              <Send size={15} />
            </button>
          </form>
        </div>
      )}

      {/* 2. FLOATING TICKING PILL BAR */}
      <div className="bg-gray-900/95 text-white backdrop-blur-xl border border-gray-700/80 rounded-2xl shadow-2xl p-2.5 flex items-center gap-3.5 hover:border-blue-500/50 transition-all">
        {/* Timer Display */}
        <div className="flex items-center gap-2 pl-2">
          <Clock size={16} className="text-blue-400" />
          <span className="font-mono font-extrabold text-base tracking-wider text-white">
            {formatTime(secondsRemaining)}
          </span>
        </div>

        {/* Focus Score Pill */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-gray-800 rounded-xl border border-gray-700 text-xs font-bold">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-green-400">{Math.round(focusScore)}%</span>
        </div>

        {/* Play/Pause Button */}
        <button
          onClick={() => setIsPaused(!isPaused)}
          className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-300 hover:text-white transition-colors"
          title={isPaused ? "Resume Timer" : "Pause Timer"}
        >
          {isPaused ? <Play size={16} className="text-green-400" /> : <Pause size={16} />}
        </button>

        {/* Picture-in-Picture Popout */}
        <button
          onClick={handleOpenPiP}
          className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-300 hover:text-white transition-colors"
          title="Picture-in-Picture Popout (Use outside browser)"
        >
          <ExternalLink size={16} />
        </button>

        {/* Floating Chat Trigger (Like Cluely) */}
        <button
          onClick={() => setIsChatOpen(!isChatOpen)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold text-xs transition-all ${
            isChatOpen
              ? "bg-blue-600 text-white shadow-md shadow-blue-500/30"
              : "bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 border border-blue-400/30"
          }`}
        >
          <Sparkles size={14} className="text-amber-300" />
          <span>Ask AI</span>
        </button>
      </div>
    </div>
  );
}
