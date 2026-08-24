"use client";

import { useEffect, useState, useCallback } from "react";
import { Sparkles, Cloud, Server, ShieldCheck, Check, ChevronDown } from "lucide-react";

export type TutoringModeType = "auto" | "cloud" | "ollama" | "offline";

interface AIModeSwitcherProps {
  compact?: boolean;
  className?: string;
  onModeChange?: (mode: TutoringModeType) => void;
}

const MODES: Array<{
  id: TutoringModeType;
  label: string;
  icon: typeof Sparkles;
  color: string;
  badgeBg: string;
  desc: string;
}> = [
  {
    id: "auto",
    label: "Auto Mode",
    icon: Sparkles,
    color: "text-[var(--primary)]",
    badgeBg: "bg-[var(--accent)] text-[var(--primary)] border-[var(--glass-border-highlight)]",
    desc: "Cloud API → Local Ollama → Offline Fallback",
  },
  {
    id: "cloud",
    label: "Cloud API",
    icon: Cloud,
    color: "text-[var(--primary)]",
    badgeBg: "bg-[var(--primary)]/10 text-[var(--primary)] border-[var(--primary)]/20",
    desc: "OpenAI, Claude, DeepSeek via cloud APIs",
  },
  {
    id: "ollama",
    label: "Local Ollama",
    icon: Server,
    color: "text-emerald-500",
    badgeBg: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
    desc: "100% private local LLM inference",
  },
  {
    id: "offline",
    label: "Offline Rules",
    icon: ShieldCheck,
    color: "text-amber-500",
    badgeBg: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
    desc: "Deterministic educational tutoring rules",
  },
];

export function AIModeSwitcher({ compact = false, className = "", onModeChange }: AIModeSwitcherProps) {
  const [activeMode, setActiveMode] = useState<TutoringModeType>("auto");
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const fetchCurrentMode = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/ai-provider/status");
      if (res.ok) {
        const data = await res.json();
        if (data.mode) {
          setActiveMode(data.mode as TutoringModeType);
        }
      }
    } catch {
      // Ignore network errors in offline state
    }
  }, []);

  useEffect(() => {
    fetchCurrentMode();
  }, [fetchCurrentMode]);

  const selectMode = async (mode: TutoringModeType) => {
    try {
      setLoading(true);
      const res = await fetch("/api/v1/ai-provider/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (res.ok) {
        setActiveMode(mode);
        setIsOpen(false);
        if (onModeChange) {
          onModeChange(mode);
        }
      }
    } catch (err) {
      console.error("Failed to switch AI mode:", err);
    } finally {
      setLoading(false);
    }
  };

  const currentModeInfo = MODES.find((m) => m.id === activeMode) || MODES[0];
  const IconComponent = currentModeInfo.icon;

  if (compact) {
    return (
      <div className={`relative inline-block ${className}`}>
        <button
          onClick={() => setIsOpen(!isOpen)}
          disabled={loading}
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors ${currentModeInfo.badgeBg} hover:opacity-90`}
          title={`Active AI Tutoring Mode: ${currentModeInfo.label}`}
        >
          <IconComponent className={`w-3.5 h-3.5 ${currentModeInfo.color}`} />
          <span>{currentModeInfo.label}</span>
          <ChevronDown className="w-3 h-3 opacity-60" />
        </button>

        {isOpen && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
            <div className="absolute right-0 mt-1.5 w-56 rounded-xl border border-[var(--border)] bg-[var(--card)] p-1.5 shadow-lg z-50 animate-in fade-in zoom-in-95 duration-100">
              <div className="px-2 py-1 text-[10px] font-semibold text-[var(--muted-foreground)] uppercase tracking-wider">
                Switch Tutoring Mode
              </div>
              {MODES.map((m) => {
                const ItemIcon = m.icon;
                const isSelected = m.id === activeMode;
                return (
                  <button
                    key={m.id}
                    onClick={() => selectMode(m.id)}
                    className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-xs transition-colors ${
                      isSelected
                        ? "bg-[var(--accent)] text-[var(--foreground)] font-medium"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50 hover:text-[var(--foreground)]"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <ItemIcon className={`w-4 h-4 ${m.color}`} />
                      <span>{m.label}</span>
                    </div>
                    {isSelected && <Check className="w-3.5 h-3.5 text-[var(--primary)]" />}
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>
    );
  }

  return (
    <div className={`flex flex-wrap gap-2 ${className}`}>
      {MODES.map((m) => {
        const ItemIcon = m.icon;
        const isSelected = m.id === activeMode;
        return (
          <button
            key={m.id}
            onClick={() => selectMode(m.id)}
            disabled={loading}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium border transition-all ${
              isSelected
                ? `${m.badgeBg} ring-2 ring-[var(--glow-primary)] shadow-sm font-semibold`
                : "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:border-[var(--foreground)]/20 hover:text-[var(--foreground)]"
            }`}
          >
            <ItemIcon className={`w-4 h-4 ${m.color}`} />
            <span>{m.label}</span>
          </button>
        );
      })}
    </div>
  );
}
