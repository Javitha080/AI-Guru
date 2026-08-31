"use client";

import { Award, Flame, Star } from "lucide-react";
import { useCountUp, useMagneticTilt } from "@/lib/motion/useGsapReveal";

interface RewardCardProps {
  level: number;
  title: string;
  currentXp: number;
  nextLevelXp: number;
  /**
   * Fill percentage, 0–100. Passed in rather than derived here so the level
   * arithmetic stays in one place (GamificationDashboard, which owns the
   * LEVEL_STEP constant mirrored from the backend).
   */
  percent: number;
  streak: number;
  recentBadges: string[];
}

export default function RewardCard({
  level,
  title,
  currentXp,
  nextLevelXp,
  percent,
  streak,
  recentBadges,
}: RewardCardProps) {
  const cardRef = useMagneticTilt<HTMLDivElement>(2);
  const xpRef = useCountUp(currentXp, 0);
  const clamped = Math.min(100, Math.max(0, percent));

  return (
    <div
      ref={cardRef}
      className="liquid-glass liquid-glass--refract liquid-glass--spotlight h-full w-full p-6 flex flex-col justify-between gap-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-4 min-w-0">
          <span
            aria-hidden="true"
            className="grid place-items-center w-14 h-14 rounded-2xl shrink-0"
            style={{ background: "var(--ember-1)", color: "var(--primary)" }}
          >
            <Star size={26} />
          </span>
          <div className="min-w-0">
            <h3 className="font-display text-2xl font-bold text-[var(--foreground)] leading-tight">
              Level {level}
            </h3>
            <p className="text-sm text-[var(--muted-foreground)] font-medium truncate">
              {title}
            </p>
          </div>
        </div>

        <span
          className="glass-capsule inline-flex items-center gap-1.5 font-bold shrink-0"
          style={{ color: "var(--primary)" }}
        >
          <Flame size={15} fill="currentColor" aria-hidden="true" />
          {streak}
          <span className="sr-only">day streak</span>
        </span>
      </div>

      <div>
        <div className="flex justify-between items-baseline text-xs mb-2">
          <span className="text-[var(--muted-foreground)] font-medium">
            {/* Tweened text is hidden from AT; the progressbar below carries
                the accessible value. */}
            <span ref={xpRef} aria-hidden="true" className="tabular-nums">
              0
            </span>{" "}
            XP
          </span>
          <span className="text-[var(--muted-foreground)] font-medium tabular-nums">
            {nextLevelXp} XP
          </span>
        </div>

        <div
          role="progressbar"
          aria-valuenow={clamped}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuetext={`${clamped}% toward level ${level + 1}`}
          aria-label="Progress to next level"
          className="h-2.5 w-full rounded-full overflow-hidden"
          style={{ background: "var(--glass-0)" }}
        >
          <div
            className="h-full rounded-full transition-[width] duration-[var(--duration-slow)] ease-[var(--ease-smooth-out)]"
            style={{
              width: `${clamped}%`,
              background: "linear-gradient(90deg, var(--primary), var(--amber))",
              boxShadow: "0 0 18px var(--glow-primary)",
            }}
          />
        </div>
      </div>

      {recentBadges.length > 0 && (
        <div>
          <h4 className="text-xs uppercase tracking-wider text-[var(--muted-foreground)] font-semibold mb-2">
            Recent badges
          </h4>
          <ul className="flex gap-2 list-none p-0 m-0">
            {recentBadges.map((badge) => (
              <li
                key={badge}
                className="glow-ring grid place-items-center w-9 h-9 rounded-full border border-[var(--glass-border)]"
                style={{ background: "var(--glass-0)", color: "var(--amber)" }}
              >
                <Award size={16} aria-hidden="true" />
                <span className="sr-only">{badge}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
