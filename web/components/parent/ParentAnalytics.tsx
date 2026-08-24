"use client";

/**
 * Analytics tab content — REAL per-student data from /parent/sessions/{id}.
 *
 * Fixes over the legacy version:
 * - Uses pFetch (the old raw fetch() hit the server-side parent gate and the
 *   tab stayed on "Loading analytics..." forever).
 * - Accepts a studentId prop (was hardcoded to "student-primary").
 * - Renders a recent-sessions list with a per-session report viewer hook.
 *
 * Ember Glass: orange study-time bars, amber focus trend, count-up counters.
 */

import React, { useEffect, useState } from "react";
import { Activity, BarChart3, BookOpen, Calendar, FileText } from "lucide-react";
import { useCountUp } from "@/lib/motion/useGsapReveal";
import { pFetch } from "@/lib/parent/parent-api";
import type { SessionSummaryRow } from "@/lib/parent/types";

interface AnalyticsPayload {
  weekly_study_time?: number[];
  focus_trend?: number[];
  session_count_week?: number;
  session_count_month?: number;
  sessions?: SessionSummaryRow[];
}

interface ParentAnalyticsProps {
  studentId: string | null;
  onViewReport?: (sessionId: string) => void;
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function ParentAnalytics({ studentId, onViewReport }: ParentAnalyticsProps) {
  const [data, setData] = useState<AnalyticsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!studentId) return;
    // Reset before refetch — intentional synchronous clear on student switch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setData(null);
    setError(null);
    (async () => {
      try {
        const res = await pFetch(`/api/v1/parent/sessions/${encodeURIComponent(studentId)}`);
        if (cancelled) return;
        if (!res.ok) {
          setError(`Failed to load analytics (${res.status}).`);
          return;
        }
        setData((await res.json()) as AnalyticsPayload);
      } catch {
        if (!cancelled) setError("Network error loading analytics.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [studentId]);

  if (!studentId) {
    return <EmptyCard label="Select a student to view analytics." />;
  }
  if (error) {
    return <EmptyCard label={error} />;
  }
  if (!data) {
    return (
      <div className="bento-cell p-6">
        <div className="h-5 w-40 rounded bg-[var(--muted)] animate-pulse mb-6" />
        <div className="grid grid-cols-2 gap-8">
          <div className="h-40 rounded-xl bg-[var(--muted)]/60 animate-pulse" />
          <div className="h-40 rounded-xl bg-[var(--muted)]/60 animate-pulse" />
        </div>
      </div>
    );
  }

  const weekly: number[] = Array.isArray(data.weekly_study_time) ? data.weekly_study_time : [];
  const focusTrend: number[] = Array.isArray(data.focus_trend) ? data.focus_trend : [];
  const sessions: SessionSummaryRow[] = Array.isArray(data.sessions) ? data.sessions : [];

  const subjectCounts = new Map<string, number>();
  for (const s of sessions) {
    const subj = String(s?.subject || "").trim();
    if (subj) subjectCounts.set(subj, (subjectCounts.get(subj) ?? 0) + 1);
  }
  const topSubjects = [...subjectCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([s]) => s);

  const maxStudyTime = Math.max(...weekly, 1);
  const hasWeekly = weekly.some((m) => m > 0);

  return (
    <div className="bento-cell liquid-sheen p-6">
      <h3 className="font-display text-lg font-bold mb-6 flex items-center gap-2 relative z-[2]">
        <Activity className="text-[var(--primary)]" size={19} />
        Weekly Analytics
      </h3>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8 relative z-[2]">
        {/* Study time bars */}
        <div>
          <h4 className="text-sm font-medium text-[var(--muted-foreground)] mb-4">Study Time — Minutes</h4>
          <div className="flex items-end gap-2 h-40">
            {!hasWeekly && (
              <div className="flex-1 self-center text-center text-xs text-[var(--muted-foreground)]">
                No study time recorded in the last 7 days.
              </div>
            )}
            {weekly.map((time, idx) => (
              <div key={idx} className="flex-1 flex flex-col items-center gap-2 h-full justify-end group/bar">
                <span className="text-[10px] text-[var(--muted-foreground)]">{time > 0 ? Math.round(time) : ""}</span>
                <div className="w-full bg-[var(--ember-0)]/50 rounded-t-md relative flex-1 flex items-end overflow-hidden border-t border-x border-[var(--glass-border)]/60">
                  <div
                    className="w-full rounded-t-md transition-all duration-500 ease-out group-hover/bar:brightness-125"
                    style={{
                      height: `${(time / maxStudyTime) * 100}%`,
                      background: "linear-gradient(180deg, #E8895F, var(--primary))",
                      boxShadow: "0 0 12px var(--glow-primary)",
                    }}
                    title={`${Math.round(time)} min`}
                  />
                </div>
                <span className="text-xs text-[var(--muted-foreground)]">{DAYS[idx]}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Focus trend bars */}
        <div>
          <h4 className="text-sm font-medium text-[var(--muted-foreground)] mb-4">Focus Trend — %</h4>
          <div className="flex items-end gap-2 h-40">
            {focusTrend.length === 0 ? (
              <div className="flex-1 self-center text-center text-xs text-[var(--muted-foreground)]">
                No completed sessions this week yet.
              </div>
            ) : (
              focusTrend.map((score, idx) => (
                <div key={idx} className="flex-1 flex flex-col items-center gap-2 h-full justify-end group/focus">
                  <div className="w-full bg-[var(--amber-glow)]/30 rounded-t-md relative flex-1 flex items-end overflow-hidden border-t border-x border-[var(--glass-border)]/60">
                    <div
                      className="w-full rounded-t-md transition-all duration-500 ease-out group-hover/focus:brightness-110"
                      style={{
                        height: `${Math.max(0, Math.min(100, score))}%`,
                        background: "linear-gradient(180deg, var(--amber), color-mix(in srgb, var(--amber) 55%, var(--primary)))",
                        boxShadow: "0 0 12px var(--amber-glow)",
                      }}
                      title={`${Math.round(score)}%`}
                    />
                  </div>
                  <span className="text-[10px] text-[var(--muted-foreground)]">{Math.round(score)}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Counters */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8 relative z-[2]">
        <Counter
          icon={<Calendar size={17} />}
          value={data.session_count_week ?? 0}
          label="Sessions this week"
          tint="var(--primary)"
        />
        <Counter
          icon={<BarChart3 size={17} />}
          value={data.session_count_month ?? 0}
          label="Sessions last 30 days"
          tint="var(--amber)"
        />
        <div className="col-span-2 rounded-xl p-4 bg-[var(--glass-0)] border border-[var(--glass-border)] flex items-start gap-3 backdrop-blur-sm">
          <BookOpen size={17} className="text-[var(--primary)] mt-0.5 shrink-0" />
          <div className="min-w-0">
            <div className="text-sm font-semibold">Top Subjects</div>
            <div className="text-xs text-[var(--muted-foreground)] flex gap-2 mt-1.5 flex-wrap">
              {topSubjects.length === 0 ? (
                <span>Complete a session to see subjects here.</span>
              ) : (
                topSubjects.map((sub) => (
                  <span
                    key={sub}
                    className="px-2 py-0.5 rounded-md bg-[var(--ember-0)] border border-[var(--glass-border)] text-[var(--foreground)]"
                  >
                    {sub}
                  </span>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Recent sessions */}
      <div className="relative z-[2]">
        <h4 className="text-sm font-medium mb-3">Recent Sessions</h4>
        {sessions.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)] py-4 text-center">
            No sessions recorded for this student yet.
          </p>
        ) : (
          <div className="divide-y divide-[var(--glass-border)] surface-glass-base rounded-xl overflow-hidden">
            {sessions.map((s) => {
              const mins = Math.round((s.actual_duration_seconds || 0) / 60);
              const started = s.start_time || s.created_at;
              return (
                <div
                  key={s.id}
                  className="flex items-center justify-between px-4 py-2.5 hover:bg-[var(--ember-0)] transition-colors gap-3"
                >
                  <div className="min-w-0">
                    <div className="text-xs font-semibold truncate flex items-center gap-2">
                      {s.subject || "General"}
                      <span
                        className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full ${
                          s.status === "completed"
                            ? "bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/30"
                            : s.status === "in_progress"
                              ? "bg-[var(--amber-glow)]/70 text-[var(--amber)] border border-[var(--amber)]/30"
                              : "bg-[var(--muted)] text-[var(--muted-foreground)] border border-[var(--glass-border)]"
                        }`}
                      >
                        {(s.status === "in_progress") && (
                          <span className="w-1 h-1 rounded-full bg-[var(--amber)] ember-dot" />
                        )}
                        {String(s.status).replace(/_/g, " ")}
                      </span>
                    </div>
                    <div className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
                      {started ? new Date(started * 1000).toLocaleString() : "—"} · {mins} min
                      {s.focus_score != null && s.focus_score > 0
                        ? ` · focus ${Math.round(s.focus_score)}%`
                        : ""}
                    </div>
                  </div>
                  {onViewReport && (
                    <button
                      onClick={() => onViewReport(s.id)}
                      className="shrink-0 px-2.5 py-1.5 text-[11px] font-semibold rounded-lg surface-glass-base glow-ring flex items-center gap-1 transition-colors hover:text-[var(--primary)]"
                    >
                      <FileText size={12} /> Report
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyCard({ label }: { label: string }) {
  return (
    <div className="bento-cell p-10 text-center text-sm text-[var(--muted-foreground)]">{label}</div>
  );
}

function Counter({
  icon,
  value,
  label,
  tint,
}: {
  icon: React.ReactNode;
  value: number;
  label: string;
  tint: string;
}) {
  const numRef = useCountUp(value, 0, "");
  return (
    <div className="rounded-xl p-4 bg-[var(--glass-0)] border border-[var(--glass-border)] flex items-start gap-3 backdrop-blur-sm transition-colors duration-200 hover:border-[var(--glass-border-highlight)]">
      <span className="mt-0.5" style={{ color: tint }}>
        {icon}
      </span>
      <div>
      <span ref={numRef} className="font-display text-xl font-bold tabular-nums block" style={{ color: tint }} />
        <div className="text-xs text-[var(--muted-foreground)]">{label}</div>
      </div>
    </div>
  );
}
