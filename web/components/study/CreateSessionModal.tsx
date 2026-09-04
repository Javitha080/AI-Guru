"use client";

/**
 * New-session sheet — LiquidGlass modal. Subject & duration as tactile
 * chip grids; entrance uses the global overlay/pop keyframes plus a GSAP
 * field stagger. Creation itself stays in the page's pre-flight handler.
 */

import { useState } from "react";
import { CalendarClock, X } from "lucide-react";
import { useRevealStagger } from "@/lib/motion/useGsapReveal";

interface CreateSessionModalProps {
  onClose: () => void;
  onStart: (title: string, subject: string, duration: number) => void;
}

const SUBJECTS = ["ICT (A/L)", "ICT (O/L)", "Computer Science", "Mathematics", "Science", "General"];
const DURATIONS = [15, 25, 30, 45, 60, 90];

export default function CreateSessionModal({ onClose, onStart }: CreateSessionModalProps) {
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("ICT (A/L)");
  const [duration, setDuration] = useState(25);
  const [isLoading, setIsLoading] = useState(false);

  const revealRoot = useRevealStagger<HTMLDivElement>([]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    const finalTitle = title.trim() || `${subject} Study Session`;
    // Session creation happens once, in the page's pre-flight completion
    // handler (single source of truth — no double-create).
    onStart(finalTitle, subject, duration);
    setIsLoading(false);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-overlay-in"
      style={{ background: "rgba(0, 0, 0, 0.70)", backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={revealRoot}
        className="liquid-glass liquid-glass--strong liquid-glass--refract relative w-full max-w-md p-7 rounded-3xl shadow-[0_30px_70px_-15px_rgba(0,0,0,0.8)] animate-pop-in overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-label="New study session"
      >
        {/* Specular Top Key-light Line */}
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-white/35 to-transparent z-20"
          aria-hidden="true"
        />

        <div className="relative z-10 flex items-center justify-between mb-6" data-reveal>
          <div className="flex items-center gap-3">
            <span className="w-10 h-10 rounded-2xl bg-[var(--ember-0)] border border-[var(--glass-border)] flex items-center justify-center text-[var(--primary)] shadow-sm">
              <CalendarClock size={20} />
            </span>
            <h2 className="font-display text-xl font-bold tracking-tight">New Study Session</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="w-8 h-8 rounded-full surface-glass-base flex items-center justify-center text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-white/10 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="relative z-10 space-y-5">
          <div data-reveal>
            <label htmlFor="session-title" className="block text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
              Title <span className="normal-case font-medium tracking-normal opacity-70">(optional)</span>
            </label>
            <input
              id="session-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="E.g., Calculus Midterm Prep"
              className="glass-input w-full"
            />
          </div>

          <div data-reveal>
            <span className="block text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">Subject</span>
            <div className="grid grid-cols-3 gap-2">
              {SUBJECTS.map((sub) => {
                const active = subject === sub;
                return (
                  <button
                    key={sub}
                    type="button"
                    onClick={() => setSubject(sub)}
                    aria-pressed={active}
                    className={`px-2.5 py-2.5 rounded-2xl text-xs font-semibold border transition-all duration-200 ${
                      active
                        ? "bg-[var(--primary)] text-white border-transparent shadow-[0_4px_16px_var(--glow-primary)] scale-[1.03]"
                        : "surface-glass-base border-[var(--glass-border)] hover:border-[var(--ember-line)]/50 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {sub}
                  </button>
                );
              })}
            </div>
          </div>

          <div data-reveal>
            <span className="block text-xs font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-2">
              Duration <span className="normal-case font-medium tracking-normal opacity-70">(minutes)</span>
            </span>
            <div className="grid grid-cols-3 gap-2">
              {DURATIONS.map((dur) => {
                const active = duration === dur;
                return (
                  <button
                    key={dur}
                    type="button"
                    onClick={() => setDuration(dur)}
                    aria-pressed={active}
                    className={`py-2.5 rounded-2xl text-sm font-bold border transition-all duration-200 ${
                      active
                        ? "bg-[var(--amber)] text-black border-transparent shadow-[0_4px_16px_var(--amber-glow)] scale-[1.03]"
                        : "surface-glass-base border-[var(--glass-border)] hover:border-[var(--amber)]/40 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {dur}m
                  </button>
                );
              })}
            </div>
          </div>

          <div className="pt-3 flex justify-end gap-2.5" data-reveal>
            <button type="button" onClick={onClose} className="glass-btn-secondary !rounded-2xl px-4 py-2 text-xs">
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="glass-btn-primary !rounded-2xl px-5 py-2 inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
            >
              <CalendarClock size={15} />
              {isLoading ? "Starting…" : "Start Session"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
