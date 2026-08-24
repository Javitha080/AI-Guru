"use client";

/**
 * Completed-session report — Ember Glass stats bento.
 * Numbers tween up via GSAP when real data lands; null stays an honest dash.
 */

import { Award, Target, AlertTriangle, ChevronRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useCountUp, useRevealStagger } from "@/lib/motion/useGsapReveal";

interface SessionStats {
  durationMinutes: number | null;
  focusScore: number | null;
  engagementScore: number | null;
  distractionCount: number | null;
  warningCount: number | null;
  xpEarned: number | null;
  badgesUnlocked: string[];
  summary: string | null;
}

interface SessionReportViewProps {
  stats: SessionStats | null;
  /** Set when the report fetch itself failed (backend unreachable etc). */
  error?: string | null;
  onHome: () => void;
}

function Stat({
  value,
  label,
  suffix,
  accent = "var(--foreground)",
  icon,
}: {
  value: number | null;
  label: string;
  suffix: string;
  accent?: string;
  icon: React.ReactNode;
}) {
  const numRef = useCountUp(value, 0, suffix);
  return (
    <div
      className="bento-cell bento-cell--hover p-4 flex flex-col items-center justify-center text-center gap-1"
      title={value === null ? "Awaiting data" : undefined}
    >
      <span className="text-[var(--muted-foreground)] mb-0.5">{icon}</span>
      <span ref={numRef} className="font-display text-2xl font-extrabold tabular-nums leading-none transition-colors duration-500" style={{ color: accent }} />
      <span className="text-[10px] text-[var(--muted-foreground)] uppercase tracking-[0.14em] font-bold mt-0.5">
        {label}
      </span>
    </div>
  );
}

export default function SessionReportView({ stats, error, onHome }: SessionReportViewProps) {
  const loading = stats === null && !error;

  // Re-run entrance when loading resolves so cards animate with data present.
  const revealRoot = useRevealStagger<HTMLDivElement>([loading, error]);

  return (
    <div ref={revealRoot} className="w-full max-w-2xl mx-auto p-6 md:p-8 relative z-10">
      <div className="text-center mb-9 text-balance" data-reveal>
        <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-[var(--muted-foreground)]">
          Session Report
        </p>
        <h1 className="font-display text-3xl font-extrabold tracking-tight mt-1.5 mb-2">
          Session{" "}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-[var(--primary)] to-[var(--amber)]">
            Complete!
          </span>
        </h1>
        <p className="text-sm text-[var(--muted-foreground)]">Great job staying focused. Here is your summary.</p>
      </div>

      {error && (
        <div
          className="mb-8 p-4 rounded-xl border border-red-500/30 bg-red-500/[0.07] text-sm text-red-300 flex items-start gap-2"
          data-reveal
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-[var(--muted-foreground)]">
          <Loader2 size={16} className="animate-spin text-[var(--primary)]" />
          Compiling your session report…
        </div>
      ) : (
        stats && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5 mb-6">
              <div data-reveal>
                <Stat value={stats.durationMinutes} label="Study Time" suffix="m" icon={<Award size={15} />} />
              </div>
              <div data-reveal>
                <Stat value={stats.focusScore} label="Focus Score" suffix="%" accent="var(--primary)" icon={<Target size={15} />} />
              </div>
              <div data-reveal>
                <Stat value={stats.engagementScore} label="Engagement" suffix="%" accent="var(--amber)" icon={<Target size={15} />} />
              </div>
              <div data-reveal>
                <Stat value={stats.xpEarned} label="XP Earned" suffix="" accent="var(--amber)" icon={<Award size={15} />} />
              </div>
            </div>

            {/* AI Summary */}
            <div className="bento-cell liquid-sheen rounded-2xl p-5 mb-6 flex items-start gap-4" data-reveal>
              <div className="p-3 bg-[var(--ember-0)] border border-[var(--glass-border)] rounded-xl shrink-0 text-[var(--primary)]">
                <Target size={22} />
              </div>
              <div className="min-w-0">
                <h3 className="font-display font-bold mb-1">AI Summary</h3>
                <p className="text-sm text-[var(--muted-foreground)] leading-relaxed whitespace-pre-line break-words">
                  {stats.summary?.trim()
                    ? stats.summary
                    : `Distractions detected: ${stats.distractionCount ?? 0}. Warnings issued: ${stats.warningCount ?? 0}.`}
                </p>
              </div>
            </div>

            {(stats.badgesUnlocked?.length ?? 0) > 0 && (
              <div className="mb-6" data-reveal>
                <h3 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)] mb-3">
                  Badges Unlocked
                </h3>
                <div className="flex gap-2.5 flex-wrap">
                  {stats.badgesUnlocked.map((badge, idx) => (
                    <span
                      key={idx}
                      className="flex items-center gap-2 bg-[var(--amber-glow)] text-[var(--amber)] px-4 py-2 rounded-full border border-[var(--amber)]/25 text-xs font-semibold shadow-[0_0_16px_var(--amber-glow)]"
                    >
                      <Award size={16} />
                      {badge}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        )
      )}

      <div className="flex flex-col sm:flex-row gap-3 justify-center mt-8" data-reveal>
        <button onClick={onHome} className="glass-btn-secondary !rounded-xl inline-flex items-center justify-center">
          Back to Study Room
        </button>
        <Link
          href="/achievements"
          className="glass-btn-primary !rounded-xl inline-flex items-center justify-center gap-2"
        >
          View Achievements <ChevronRight size={17} />
        </Link>
      </div>
    </div>
  );
}
