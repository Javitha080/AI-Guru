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
import type { IncidentItem, StudentRow, TunnelSnapshot } from "@/lib/parent/types";

interface OverviewTabProps {
  students: StudentRow[];
  incidents: IncidentItem[];
  incidentsLoading: boolean;
  selectedStudentId: string | null;
  onSelectStudent: (studentId: string) => void;
  onOpenReports: (studentId: string) => void;
  onLiveView: (student: StudentRow) => void;
  onSendTunnelLink: () => void;
  tunnel: TunnelSnapshot;
  tunnelBusy: boolean;
  onToggleTunnel: () => void;
}

export default function OverviewTab({
  students, incidents, incidentsLoading, selectedStudentId,
  onSelectStudent, onOpenReports, onLiveView, onSendTunnelLink, tunnel, tunnelBusy, onToggleTunnel,
}: OverviewTabProps) {
  const active = tunnel.status === "active" && tunnel.url_is_public;
  const pending = tunnel.status === "starting" || tunnel.status === "reconnecting";
  const degraded = !active && !pending;
  // Honest reason line: backend-provided message (download progress, failure,
  // give-up) wins; otherwise fall back to the LAN hint.
  const reasonLine = degraded
    ? tunnel.message ||
      (tunnel.url
        ? `${tunnel.url}/parent (local only)`
        : `LAN only · http://<your-ip>:${tunnel.local_port ?? ""}/parent`)
    : active && tunnel.url
      ? `${tunnel.url}/parent`
      : `LAN only · http://<your-ip>:${tunnel.local_port ?? ""}/parent`;

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
                {tunnel.status.toUpperCase()}
              </span>
            </div>
            <p
              className={`text-xs font-mono mt-0.5 break-all ${
                degraded && tunnel.message
                  ? "text-[var(--amber)]"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              {reasonLine}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {tunnel.url_is_public && (
            <button
              onClick={onSendTunnelLink}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--amber-glow)]/60 hover:bg-[var(--amber-glow)] text-[var(--amber)] border border-[var(--amber)]/35 text-xs font-semibold transition-colors glow-ring"
            >
              <Send size={13} />
              <span>Link via Telegram</span>
            </button>
          )}
          <button
            onClick={onToggleTunnel}
            disabled={tunnelBusy}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50 ${
              active
                ? "surface-glass-base hover:border-red-500/40 hover:text-red-300"
                : "bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white shadow-[0_4px_16px_var(--glow-primary)] hover:brightness-110 active:scale-95"
            }`}
          >
            {tunnelBusy ? "Working…" : active ? "Stop Tunnel" : "Start Tunnel"}
          </button>
        </div>
      </div>

      {/* Student bento cells */}
      {students.length === 0 ? (
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
                            ? student.current_subject || "Studying"
                            : "Not studying right now"}
                        </p>
                      </div>
                    </div>
                    {student.status === "studying" ? (
                      <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/40 flex items-center gap-1.5 shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary)] ember-dot" />
                        Studying
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
        <h3 className="font-display text-lg font-bold mb-5 flex items-center gap-2">
          <ShieldAlert className="text-[var(--primary)]" size={19} />
          <span>Distraction &amp; Warning Timeline{selectedStudentId ? "" : " (select a student)"}</span>
        </h3>

        {incidentsLoading ? (
          <div className="py-8 text-center text-[var(--muted-foreground)] text-sm">Loading incidents…</div>
        ) : incidents.length === 0 ? (
          <div className="py-8 text-center text-[var(--muted-foreground)]">
            <ShieldAlert size={30} className="mx-auto mb-2 opacity-40" />
            <p className="text-sm">No incidents recorded yet. Warnings from monitored sessions will appear here.</p>
          </div>
        ) : (
          <div className="relative pl-7 space-y-3 before:absolute before:left-[9px] before:top-2 before:bottom-2 before:w-px before:bg-[var(--glass-border-highlight)]">
            {incidents.map((item, idx) => {
              const sev = String(item.severity || "warning");
              const nodeColor =
                sev === "alert" ? "var(--destructive)" : sev === "warning" ? "var(--amber)" : "var(--primary)";
              const tag =
                sev === "alert" ? "Alert sent" : sev === "warning" ? "Warning logged" : "Logged";
              return (
                <div key={`${item.timestamp}-${idx}`} className="relative animate-pop-in">
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
                          <span className="text-xs font-mono text-[var(--muted-foreground)]">({item.time})</span>
                        </div>
                        <p className="text-xs text-[var(--muted-foreground)] mt-0.5 truncate">
                          {item.message ||
                            `Confidence ${Math.round((item.confidence || 0) * 100)}% · ${Math.round(item.duration_seconds || 0)}s`}
                        </p>
                      </div>
                    </div>
                    <span className="text-[11px] px-2.5 py-1 rounded-full font-medium bg-[var(--muted)] text-[var(--muted-foreground)] border border-[var(--glass-border)] shrink-0">
                      {tag}
                    </span>
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
