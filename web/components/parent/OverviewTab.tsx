"use client";

/**
 * Overview tab — Ember Glass bento dashboard.
 * Remote-access gateway tile, live student bento cells (real metrics,
 * honest "—" when never measured) and a severity-rail incident timeline.
 */

import React from "react";
import {
  Award, Clock, FileText, Flame, Radio, Send, ShieldAlert, Sparkles, Video,
} from "lucide-react";
import { useRevealStagger } from "@/lib/motion/useGsapReveal";
import type { IncidentItem, OutboxSnapshot, StudentRow, TunnelSnapshot } from "@/lib/parent/types";

interface OverviewTabProps {
  students: StudentRow[];
  studentsError?: string | null;
  onRetryStudents?: () => void;
  incidents: IncidentItem[];
  incidentsLoading: boolean;
  selectedStudentId: string | null;
  onSelectStudent: (studentId: string) => void;
  onOpenReports: (studentId: string) => void;
  onLiveView: (student: StudentRow) => void;
  onSendTunnelLink: () => void;
  sendLinkStatus?: { ok: boolean; text: string } | null;
  tunnel: TunnelSnapshot;
  tunnelBusy: boolean;
  onToggleTunnel: () => void;
  outbox?: OutboxSnapshot | null;
}

const TUNNEL_LABELS: Record<string, string> = {
  active: "Active",
  starting: "Starting",
  reconnecting: "Reconnecting",
  inactive: "Inactive",
  local_only: "LAN only",
  failed: "Failed",
  error: "Error",
};

export default function OverviewTab({
  students, studentsError, onRetryStudents, incidents, incidentsLoading, selectedStudentId,
  onSelectStudent, onOpenReports, onLiveView, onSendTunnelLink, sendLinkStatus, tunnel, tunnelBusy, onToggleTunnel, outbox,
}: OverviewTabProps) {
  const [severityFilter, setSeverityFilter] = React.useState<"all" | "alert" | "warning" | "info">("all");
  const active = tunnel.status === "active" && tunnel.url_is_public;
  const pending = tunnel.status === "starting" || tunnel.status === "reconnecting";
  const failed = tunnel.status === "failed" || tunnel.status === "error";
  const lanOnly = tunnel.status === "local_only" || (!active && !pending && !failed);
  // Honest reason line: backend portal_hint (public URL) wins when active;
  // backend message (negotiation progress / failure) second; LAN fallback
  // uses the real port when known, never a broken ":/parent" placeholder.
  const portalLink = tunnel.portal_hint || (active && tunnel.url ? `${tunnel.url}/parent` : null);
  const lanLine = tunnel.local_port
    ? `LAN only · http://<your-ip>:${tunnel.local_port}/parent (same Wi-Fi)`
    : `LAN only · same Wi-Fi — start the tunnel for remote access`;
  const reasonLine = active && portalLink ? portalLink : tunnel.message || lanLine;
  const showSendLink = !pending; // LAN links are sendable too (marked home-Wi-Fi-only)
  const filteredIncidents = severityFilter === "all"
    ? incidents
    : incidents.filter((i) => String(i.severity || "warning") === severityFilter);

  // Fresh staggered entrance each time this tab mounts.
  const revealRoot = useRevealStagger<HTMLDivElement>([]);

  return (
    <div ref={revealRoot} className="space-y-5">
      {/* Remote Access Gateway tile */}
      <div
        className={`bento-cell liquid-sheen p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 ${
          active ? "shadow-[var(--glass-shadow),0_0_28px_var(--glow-primary)]" : ""
        }`}
        data-reveal
      >
        <div className="flex items-center gap-3 min-w-0">
          <div
            className={`p-2.5 rounded-xl flex items-center justify-center border transition-colors duration-300 ${
              active
                ? "bg-[var(--primary)]/20 text-[var(--primary)] border-[var(--ember-line)]/50 shadow-[0_0_18px_var(--glow-primary)]"
                : tunnel.status === "starting" || tunnel.status === "reconnecting"
                  ? "bg-[var(--amber-glow)]/60 text-[var(--amber)] border-[var(--amber)]/35"
                  : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--glass-border)]"
            }`}
          >
            <Radio size={19} className={pending ? "animate-pulse" : undefined} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h4 className="font-bold text-sm">Remote Access Gateway</h4>
              <span
                className={`px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
                  active
                    ? "bg-[var(--ember-0)] text-[var(--primary)] border-[var(--ember-line)]/40"
                    : pending
                      ? "bg-[var(--amber-glow)]/70 text-[var(--amber)] border-[var(--amber)]/30"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--glass-border)]"
                }`}
              >
                {TUNNEL_LABELS[tunnel.status] ?? tunnel.status.toUpperCase()}
              </span>
              {tunnel.provider && (
                <span className="text-[11px] text-[var(--muted-foreground)] font-mono">
                  {tunnel.provider}
                  {typeof tunnel.restart_attempts === "number" && tunnel.restart_attempts > 0
                    ? ` · retry ${tunnel.restart_attempts}`
                    : ""}
                </span>
              )}
            </div>
            {portalLink ? (
              <a
                href={portalLink}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-mono mt-0.5 break-all text-[var(--primary)] hover:underline"
              >
                {portalLink}
              </a>
            ) : (
              <p
                className={`text-xs font-mono mt-0.5 break-all ${
                  !lanOnly && tunnel.message
                    ? "text-[var(--amber)]"
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                {reasonLine}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {showSendLink && (
            <button
              onClick={onSendTunnelLink}
              title={active ? "Send the public portal link" : "Send the LAN portal link (home Wi-Fi only)"}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--amber-glow)]/60 hover:bg-[var(--amber-glow)] text-[var(--amber)] border border-[var(--amber)]/35 text-xs font-semibold transition-colors glow-ring"
            >
              <Send size={13} />
              <span>Link via Telegram{active ? "" : " (Wi-Fi)"}</span>
            </button>
          )}
          <button
            onClick={onToggleTunnel}
            disabled={tunnelBusy || pending}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50 ${
              active
                ? "surface-glass-base hover:border-red-500/40 hover:text-red-300"
                : "bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white shadow-[0_4px_16px_var(--glow-primary)] hover:brightness-110 active:scale-95"
            }`}
          >
            {tunnelBusy || pending ? "Working…" : active ? "Stop Tunnel" : failed ? "Retry Tunnel" : "Start Tunnel"}
          </button>
        </div>
      </div>
      {sendLinkStatus && (
        <p
          className={`text-xs font-semibold px-3.5 py-2.5 rounded-xl border animate-pop-in ${
            sendLinkStatus.ok
              ? "text-[var(--primary)] bg-[var(--ember-0)] border-[var(--ember-line)]/35"
              : "text-red-300 bg-red-500/[0.08] border-red-500/30"
          }`}
          data-reveal
        >
          {sendLinkStatus.text}
        </p>
      )}
      {outbox && (outbox.pending > 0 || outbox.sending > 0 || outbox.dead > 0) && (
        <p
          className="text-xs font-semibold px-3.5 py-2.5 rounded-xl border animate-pop-in text-[var(--amber)] bg-[var(--amber-glow)]/50 border-[var(--amber)]/35"
          data-reveal
        >
          {outbox.pending + outbox.sending > 0
            ? `${outbox.pending + outbox.sending} Telegram alert(s) queued offline — they will deliver automatically when the connection recovers.`
            : ""}
          {outbox.dead > 0
            ? `${outbox.pending + outbox.sending > 0 ? " " : ""}${outbox.dead} alert(s) failed permanently — check Telegram setup in Settings.`
            : ""}
          {typeof outbox.overall_pending === "number" && outbox.overall_pending > outbox.pending
            ? ` (${outbox.overall_pending} total across parents)`
            : ""}
        </p>
      )}

      {/* Student bento cells */}
      {studentsError && students.length === 0 ? (
        <div className="py-12 text-center space-y-3" data-reveal>
          <p className="text-[var(--muted-foreground)] text-sm">{studentsError}</p>
          {onRetryStudents && (
            <button
              onClick={onRetryStudents}
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white text-xs font-bold hover:brightness-110 active:scale-95 transition-all"
            >
              Retry
            </button>
          )}
        </div>
      ) : students.length === 0 ? (
        <div className="py-12 text-center text-[var(--muted-foreground)] text-sm" data-reveal>
          Loading students…
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {students.map((student) => {
            const selected = selectedStudentId === student.student_id;
            return (
              <div
                key={student.student_id}
                data-reveal
                onClick={() => onSelectStudent(student.student_id)}
                className={`bento-cell bento-cell--hover cursor-pointer overflow-hidden ${selected ? "bento-cell--selected" : ""}`}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") onSelectStudent(student.student_id);
                }}
                aria-pressed={selected}
              >
                <div className="p-5 space-y-4 relative z-[2]">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <div
                        className={`w-11 h-11 rounded-xl flex items-center justify-center font-display font-extrabold text-base shrink-0 border transition-shadow duration-300 ${
                          student.status === "studying"
                            ? "bg-gradient-to-br from-[var(--primary)] to-[#E8895F] text-white border-transparent shadow-[0_0_18px_var(--glow-primary)]"
                            : "bg-[var(--ember-0)] text-[var(--primary)] border-[var(--glass-border)]"
                        }`}
                      >
                        {(student.name || "?").charAt(0).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <h3 className="font-display font-bold text-base truncate">{student.name}</h3>
                        <p
                          className={`text-xs font-medium truncate ${
                            student.status === "studying" ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"
                          }`}
                        >
                          {student.status === "studying"
                            ? student.session_status === "paused"
                              ? `Paused · ${student.current_subject || "Studying"}`
                              : student.current_subject || "Studying"
                            : "Not studying right now"}
                        </p>
                      </div>
                    </div>
                    {student.status === "studying" ? (
                      <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/40 flex items-center gap-1.5 shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary)] ember-dot" />
                        {student.monitoring_live ? "Studying · Live" : "Studying"}
                      </span>
                    ) : (
                      <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[var(--muted)] text-[var(--muted-foreground)] border border-[var(--glass-border)] flex items-center gap-1.5 shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-[var(--muted-foreground)]/60" />
                        Offline
                      </span>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-2.5 pt-1">
                    <Metric icon={<Clock size={13} />} label="Today" value={`${student.today_study_time ?? 0} min`} />
                    <Metric
                      icon={<Flame size={13} />}
                      label="Streak"
                      value={`${student.streak ?? 0} days`}
                      tint="var(--amber)"
                      glow="var(--amber-glow)"
                    />
                    <Metric
                      icon={<Award size={13} />}
                      label={`Level ${student.level ?? 1}`}
                      value={`${student.xp ?? 0} XP`}
                      tint="var(--primary)"
                      glow="var(--glow-primary)"
                    />
                    <Metric
                      icon={<Sparkles size={13} />}
                      label="Focus"
                      value={
                        student.focus_score === null || student.focus_score === undefined
                          ? "—"
                          : `${Math.round(student.focus_score)}%`
                      }
                      tint="var(--amber)"
                      glow="var(--amber-glow)"
                    />
                  </div>
                </div>

                <div className="p-3.5 pt-3 border-t border-[var(--glass-border)] flex gap-2 relative z-[2]">
                  <button
                    onClick={(e) => { e.stopPropagation(); onSelectStudent(student.student_id); onOpenReports(student.student_id); }}
                    className="flex-1 py-2 px-3 surface-glass-base !rounded-xl text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 hover:text-[var(--primary)]"
                  >
                    <FileText size={14} />
                    <span>Reports</span>
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); onLiveView(student); }}
                    className="flex-1 py-2 px-3 rounded-xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white text-xs font-semibold flex items-center justify-center gap-1.5 shadow-[0_4px_16px_var(--glow-primary)] transition-all hover:brightness-110 active:scale-95"
                  >
                    <Video size={14} />
                    <span>Live Supervise</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Incident timeline — severity rail */}
      <div className="bento-cell p-6" data-reveal>
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-display text-lg font-bold flex items-center gap-2">
            <ShieldAlert className="text-[var(--primary)]" size={19} />
            <span>Distraction &amp; Warning Timeline{selectedStudentId ? "" : " (select a student)"}</span>
          </h3>
          {incidents.length > 0 && (
            <div className="flex gap-1.5" role="group" aria-label="Filter by severity">
              {(["all", "alert", "warning", "info"] as const).map((sev) => (
                <button
                  key={sev}
                  onClick={() => setSeverityFilter(sev)}
                  aria-pressed={severityFilter === sev}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-bold capitalize transition-all ${
                    severityFilter === sev
                      ? "bg-[var(--primary)] text-white shadow-[0_4px_14px_var(--glow-primary)]"
                      : "surface-glass-base text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {sev}
                </button>
              ))}
            </div>
          )}
        </div>

        {incidentsLoading ? (
          <div className="py-8 text-center text-[var(--muted-foreground)] text-sm">Loading incidents…</div>
        ) : incidents.length === 0 ? (
          <div className="py-8 text-center text-[var(--muted-foreground)]">
            <ShieldAlert size={30} className="mx-auto mb-2 opacity-40" />
            <p className="text-sm">No incidents recorded yet. Warnings from monitored sessions will appear here.</p>
          </div>
        ) : filteredIncidents.length === 0 ? (
          <div className="py-8 text-center text-[var(--muted-foreground)]">
            <p className="text-sm">No {severityFilter} incidents — try another filter.</p>
          </div>
        ) : (
          <div className="relative pl-7 space-y-3 before:absolute before:left-[9px] before:top-2 before:bottom-2 before:w-px before:bg-[var(--glass-border-highlight)]">
            {filteredIncidents.map((item, idx) => {
              const sev = String(item.severity || "warning");
              const nodeColor =
                sev === "alert" ? "var(--destructive)" : sev === "warning" ? "var(--amber)" : "var(--primary)";
              const tag =
                sev === "alert" ? "Alert sent" : sev === "warning" ? "Warning logged" : "Logged";
              const fullDate = item.timestamp ? new Date(item.timestamp * 1000).toLocaleString() : item.time;
              return (
                <div key={`${item.session_id}-${item.timestamp}-${idx}`} className="relative animate-pop-in">
                  {/* Rail node */}
                  <span
                    aria-hidden
                    className="absolute -left-7 top-1/2 -translate-y-1/2 w-[9px] h-[9px] rounded-full ring-4 ring-[var(--background)]"
                    style={{ background: nodeColor, boxShadow: `0 0 10px ${nodeColor}` }}
                  />
                  <div className="flex items-center justify-between gap-3 p-3.5 rounded-xl surface-glass-base transition-colors duration-200 hover:border-[var(--glass-border-highlight)]">
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className="p-2 rounded-lg shrink-0"
                        style={{
                          color: nodeColor,
                          background: `color-mix(in srgb, ${nodeColor} 12%, transparent)`,
                          border: `1px solid color-mix(in srgb, ${nodeColor} 32%, transparent)`,
                        }}
                      >
                        <ShieldAlert size={15} />
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-semibold text-sm">{item.event}</span>
                          <span className="text-xs font-mono text-[var(--muted-foreground)]" title={fullDate}>({item.time})</span>
                        </div>
                        <p className="text-xs text-[var(--muted-foreground)] mt-0.5 truncate" title={item.message || undefined}>
                          {item.message ||
                            `Confidence ${Math.round((item.confidence || 0) * 100)}% · ${Math.round(item.duration_seconds || 0)}s`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[11px] px-2.5 py-1 rounded-full font-medium bg-[var(--muted)] text-[var(--muted-foreground)] border border-[var(--glass-border)]">
                        {tag}
                      </span>
                      {selectedStudentId && (
                        <button
                          onClick={() => onOpenReports(selectedStudentId)}
                          className="text-[11px] px-2.5 py-1 rounded-full font-semibold surface-glass-base glow-ring hover:text-[var(--primary)] transition-colors"
                          title="Open session reports"
                        >
                          Reports
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  tint,
  glow,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tint?: string;
  glow?: string;
}) {
  return (
    <div className="rounded-xl p-2.5 bg-[var(--glass-0)] border border-[var(--glass-border)] backdrop-blur-sm transition-colors duration-200 hover:border-[var(--glass-border-highlight)]">
      <div className="flex items-center gap-1.5 text-[var(--muted-foreground)] text-[11px] mb-0.5">
        <span style={tint ? { color: tint } : undefined}>{icon}</span>
        <span>{label}</span>
      </div>
      <div
        className="text-base font-bold font-display"
        style={tint && glow ? { color: tint, textShadow: `0 0 14px ${glow}` } : undefined}
      >
        {value}
      </div>
    </div>
  );
}
