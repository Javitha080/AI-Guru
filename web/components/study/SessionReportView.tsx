"use client";

/**
 * Completed-session report — Ember Glass stats bento.
 * Numbers tween up via GSAP when real data lands; null stays an honest dash.
 */

import { Award, Target, AlertTriangle, ChevronRight } from "lucide-react";
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
  reportReason?: string;
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
            complete
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
        <div role="status" aria-busy="true" className="mb-6">
          <span className="sr-only">Compiling your session report…</span>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5 mb-6" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="bento-cell p-4 flex flex-col items-center justify-center gap-2">
                <div className="h-3.5 w-3.5 rounded-full bg-[var(--muted)] animate-pulse" />
                <div className="h-7 w-16 rounded-md bg-[var(--muted)] animate-pulse" />
                <div className="h-2.5 w-20 rounded bg-[var(--muted)] animate-pulse" />
              </div>
            ))}
          </div>
          <div className="bento-cell rounded-2xl p-5 flex items-start gap-4" aria-hidden="true">
            <div className="h-[46px] w-[46px] rounded-xl bg-[var(--muted)] animate-pulse shrink-0" />
            <div className="flex-1 space-y-2 py-1">
              <div className="h-3.5 w-24 rounded bg-[var(--muted)] animate-pulse" />
              <div className="h-3 w-full rounded bg-[var(--muted)] animate-pulse" />
              <div className="h-3 w-5/6 rounded bg-[var(--muted)] animate-pulse" />
            </div>
          </div>
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
                    : stats.reportReason === "abandoned"
                      ? "Session was abandoned — no summary generated."
                      : stats.reportReason === "in_progress"
                        ? "Session is still open — finish it to generate the full report."
                        : stats.focusScore === null && stats.engagementScore === null
                          ? "Focus could not be measured — monitoring was not active or the session was too short."
                          : `Distractions detected: ${stats.distractionCount ?? "—"}. Warnings issued: ${stats.warningCount ?? "—"}.`}
                </p>
                {(stats.durationMinutes === null || stats.focusScore === null) && (
                  <p className="mt-2 text-[11px] text-[var(--muted-foreground)] opacity-80">
                    Dashes (—) mean unmeasured, not zero.
                  </p>
                )}
              </div>
            </div>

            {(stats.badgesUnlocked?.length ?? 0) > 0 && (
              <div className="mb-6" data-reveal>
                <h3 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)] mb-3">
                  Badges Unlocked
                </h3>
                <div className="flex gap-2.5 flex-wrap">
                  {stats.badgesUnlocked.map((badge, idx) => {
                    const isNewest = idx === stats.badgesUnlocked.length - 1;
                    return (
                      <span
                        key={idx}
                        className={`flex items-center gap-2 px-4 py-2 rounded-full border text-xs font-semibold ${
                          isNewest
                            ? "bg-[var(--amber-glow)] text-[var(--amber)] border-[var(--amber)]/25 shadow-[0_0_16px_var(--amber-glow)]"
                            : "bg-[var(--muted)] text-[var(--foreground)] border-[var(--glass-border)]"
                        }`}
                      >
                        <Award size={16} />
                        {badge}
                      </span>
                    );
                  })}
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
