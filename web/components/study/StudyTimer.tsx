"use client";

/**
 * Ember Glass session timer — conic ring in deep orange, amber under 25%,
 * red under 10%. Breathing pulse while paused; instant states when the OS
 * prefers reduced motion.
 */

import { useEffect, useRef } from "react";
import { Pause, Play } from "lucide-react";
import gsap from "gsap";
import { motionOK } from "@/lib/motion/useGsapReveal";
import AnimatedNumber from "@/components/ui/AnimatedNumber";

interface StudyTimerProps {
  /** Seconds remaining; null = clock not started yet. */
  timeLeft: number | null;
  totalSeconds: number;
  isPaused: boolean;
  onTogglePause: () => void;
}

const RADIUS = 120;
const CIRC = 2 * Math.PI * RADIUS;

export default function StudyTimer({
  timeLeft,
  totalSeconds,
  isPaused,
  onTogglePause,
}: StudyTimerProps) {
  const safeTotal = Math.max(1, totalSeconds);
  const remaining = timeLeft ?? safeTotal;
  const progress = Math.min(1, Math.max(0, remaining / safeTotal));

  let accent = "var(--primary)";
  if (progress < 0.1) accent = "var(--destructive)";
  else if (progress < 0.25) accent = "var(--amber)";

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Entrance pop.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || !motionOK()) return;
    const tween = gsap.fromTo(
      el,
      { autoAlpha: 0, scale: 0.93 },
      { autoAlpha: 1, scale: 1, duration: 0.65, ease: "power3.out" }
    );
    return () => {
      tween.kill();
      // Restore visibility/opacity so a killed-mid-flight tween never
      // leaves the clock stuck at autoAlpha: 0 (visibility: hidden).
      gsap.set(el, { clearProps: "all" });
    };
  }, []);

  // Breathing dim while paused; restore immediately on resume.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || !motionOK()) return;
    if (isPaused) {
      const pulse = gsap.to(el, {
        opacity: 0.62,
        duration: 1.1,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });
      return () => {
        pulse.kill();
        gsap.set(el, { opacity: 1 });
      };
    }
    gsap.killTweensOf(el);
    gsap.set(el, { opacity: 1 });
  }, [isPaused]);

  return (
    <div className="flex flex-col items-center justify-center">
      <div ref={wrapRef} className="relative w-60 h-60 flex items-center justify-center">
        {/* Ambient halo behind the ring */}
        <div
          aria-hidden
          className="absolute inset-6 rounded-full blur-2xl transition-colors duration-500"
          style={{ background: accent, opacity: 0.12 }}
        />
        <svg className="absolute inset-0 w-full h-full -rotate-90" viewBox="0 0 256 256">
          <circle
            cx="128"
            cy="128"
            r={RADIUS}
            fill="none"
            stroke="var(--glass-border)"
            strokeWidth="11"
          />
          {/* Track highlight just inside the base ring */}
          <circle
            cx="128"
            cy="128"
            r={RADIUS}
            fill="none"
            stroke="var(--glass-border-highlight)"
            strokeWidth="1"
            opacity="0.5"
          />
          <circle
            cx="128"
            cy="128"
            r={RADIUS}
            fill="none"
            stroke={accent}
            strokeWidth="11"
            strokeLinecap="round"
            strokeDasharray={CIRC}
            strokeDashoffset={CIRC * (1 - progress)}
            style={{
              transition:
                "stroke-dashoffset 0.35s linear, stroke 0.5s ease",
              filter: "drop-shadow(0 0 8px currentColor)",
              color: accent,
            }}
          />
        </svg>
        <div className="relative z-10 flex flex-col items-center gap-1">
          <span
            className="font-display text-[52px] leading-none font-extrabold tabular-nums tracking-tight transition-colors duration-500"
            style={{ color: accent }}
          >
            <AnimatedNumber value={formatTime(remaining)} />
          </span>
          <span className="text-[10px] uppercase tracking-[0.24em] text-[var(--muted-foreground)] font-bold">
            {isPaused ? "Paused" : "Remaining"}
          </span>
        </div>
      </div>

      <button
        onClick={onTogglePause}
        className="glow-ring mt-6 flex items-center gap-2 px-6 py-2.5 rounded-full surface-glass-base font-semibold transition-colors hover:text-[var(--primary)]"
      >
        {isPaused ? (
          <Play size={18} fill="currentColor" />
        ) : (
          <Pause size={18} fill="currentColor" />
        )}
        <span>{isPaused ? "Resume" : "Pause"}</span>
      </button>
    </div>
  );
}
