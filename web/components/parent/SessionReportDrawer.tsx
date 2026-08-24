"use client";

/**
 * Session report drawer — renders the REAL stored report from
 * /parent/reports/{session_id}. When no report exists yet (session still
 * running / not generated), shows the honest telemetry summary + message
 * instead of fabricating scores. Ember Glass bottom-sheet.
 */

import React, { useEffect, useState } from "react";
import { AlertTriangle, FileText, Loader2, X } from "lucide-react";
import { pFetch } from "@/lib/parent/parent-api";

interface ReportPayload {
  session_id?: string;
  available?: boolean;
  focus_score?: number;
  engagement_score?: number;
  total_study_seconds?: number;
  productive_seconds?: number;
  distracted_seconds?: number;
  topics_covered_json?: string | string[];
  key_strengths?: string;
  areas_for_improvement?: string;
  ai_tutor_feedback?: string;
  generated_at?: number;
  telemetry_summary?: { total?: number; by_type?: Record<string, number> };
  message?: string;
  // get_session_report fallback shape (metrics object)
  metrics?: {
    focus_score?: number;
    engagement_score?: number;
    distraction_count?: number;
    warning_count?: number;
    actual_duration_seconds?: number;
    subject?: string;
  };
}

interface SessionReportDrawerProps {
  sessionId: string | null;
  onClose: () => void;
}

export default function SessionReportDrawer({ sessionId, onClose }: SessionReportDrawerProps) {
  const [report, setReport] = useState<ReportPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      // Drawer closed — clear report state synchronously.
      /* eslint-disable react-hooks/set-state-in-effect */
      setReport(null);
      setError(null);
      /* eslint-enable react-hooks/set-state-in-effect */
      return;
    }
    let cancelled = false;
    setReport(null);
    setError(null);
    (async () => {
      try {
        const res = await pFetch(`/api/v1/parent/reports/${encodeURIComponent(sessionId)}`);
        if (cancelled) return;
        if (!res.ok) {
          setError(`Failed to load report (${res.status}).`);
          return;
        }
        setReport((await res.json()) as ReportPayload);
      } catch {
        if (!cancelled) setError("Network error loading report.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (!sessionId) return null;

  const storedMetrics = report?.metrics ?? {};
  const focus = report?.available ? report.focus_score : storedMetrics.focus_score ?? undefined;
  const engagement = report?.available ? report.engagement_score : storedMetrics.engagement_score ?? undefined;
  const totalSeconds =
    (report?.available ? report.total_study_seconds : undefined) ??
    storedMetrics.actual_duration_seconds ??
    0;
  const productive = report?.productive_seconds;
  const distracted = report?.distracted_seconds;

  let topics: string[] = [];
  const rawTopics = report?.topics_covered_json;
  if (Array.isArray(rawTopics)) topics = rawTopics.map(String);
  else if (typeof rawTopics === "string") {
    try {
      const parsed = JSON.parse(rawTopics);
      if (Array.isArray(parsed)) topics = parsed.map(String);
    } catch {
      /* ignore malformed */
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-end sm:items-center justify-center p-0 sm:p-4 animate-overlay-in"
      style={{ background: "var(--overlay)", backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)" }}
      role="dialog"
      aria-modal="true"
    >
      <div className="w-full sm:max-w-lg max-h-[85vh] overflow-y-auto bento-cell !rounded-t-3xl sm:!rounded-3xl animate-pop-in">
        <div className="sticky top-0 z-[3] px-5 py-4 border-b border-[var(--glass-border)] flex items-center justify-between gap-3 surface-glass-base rounded-t-3xl">
          <div className="flex items-center gap-2.5 min-w-0">
            <FileText size={17} className="text-[var(--primary)] shrink-0" />
            <div className="min-w-0">
              <h3 className="font-display font-bold text-sm">Session Report</h3>
              <p className="text-[11px] text-[var(--muted-foreground)] font-mono truncate">{sessionId}</p>
            </div>
          </div>
          <button onClick={onClose} className="glass-btn-ghost" aria-label="Close report">
            <X size={18} />
          </button>
        </div>

        <div className="p-5 space-y-4 relative z-[2]">
          {error && (
            <p className="text-xs text-red-300 bg-red-500/[0.08] border border-red-500/30 rounded-xl px-3 py-2.5 flex items-center gap-2">
              <AlertTriangle size={14} /> {error}
            </p>
          )}

          {!report && !error && (
            <div className="flex items-center justify-center py-10">
              <Loader2 size={20} className="animate-spin text-[var(--primary)]" />
            </div>
          )}

          {report && (
            <>
              {report.available ? (
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Focus Score" value={focus != null ? `${Math.round(focus)}%` : "—"} tint="var(--primary)" />
                  <Stat label="Engagement" value={engagement != null ? `${Math.round(engagement)}%` : "—"} tint="var(--amber)" />
                  <Stat label="Total Study" value={`${Math.round(totalSeconds / 60)} min`} />
                  <Stat
                    label="Productive / Distracted"
                    value={
                      productive != null && distracted != null
                        ? `${Math.round(productive / 60)} / ${Math.round(distracted / 60)} min`
                        : "—"
                    }
                  />
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-[var(--amber-glow)]/40 border border-[var(--amber)]/25 text-xs text-[var(--foreground)] space-y-1.5">
                  <strong className="block text-[var(--amber)]">Report not generated yet</strong>
                  <span>{report.message || "The report is generated when the study session completes."}</span>
                  {storedMetrics.subject && (
                    <span className="block text-[var(--muted-foreground)]">Subject: {storedMetrics.subject}</span>
                  )}
                  {(report.telemetry_summary?.total ?? 0) > 0 && (
                    <span className="block text-[var(--muted-foreground)]">
                      Monitoring events so far: {report.telemetry_summary?.total}
                      {report.telemetry_summary?.by_type &&
                        Object.entries(report.telemetry_summary.by_type)
                          .map(([k, v]) => ` · ${k.replace(/_/g, " ").toLowerCase()}: ${v}`)}
                    </span>
                  )}
                </div>
              )}

              {topics.length > 0 && (
                <Section title="Topics Covered">
                  <div className="flex flex-wrap gap-1.5">
                    {topics.map((t, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 text-[11px] rounded-md bg-[var(--ember-0)] border border-[var(--glass-border)]"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </Section>
              )}

              {report.key_strengths && (
                <Section title="Key Strengths"><Body text={report.key_strengths} /></Section>
              )}
              {report.areas_for_improvement && (
                <Section title="Areas for Improvement"><Body text={report.areas_for_improvement} /></Section>
              )}
              {report.ai_tutor_feedback && (
                <Section title="AI Tutor Feedback"><Body text={report.ai_tutor_feedback} /></Section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, tint }: { label: string; value: string; tint?: string }) {
  return (
    <div className="rounded-xl p-3 bg-[var(--glass-0)] border border-[var(--glass-border)] backdrop-blur-sm">
      <div className="text-[11px] text-[var(--muted-foreground)] mb-0.5">{label}</div>
      <div className="font-display text-base font-bold" style={tint ? { color: tint } : undefined}>
        {value}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-bold uppercase tracking-wide text-[var(--muted-foreground)] mb-1.5">{title}</h4>
      {children}
    </div>
  );
}

function Body({ text }: { text: string }) {
  return <p className="text-xs leading-relaxed whitespace-pre-line">{text}</p>;
}
