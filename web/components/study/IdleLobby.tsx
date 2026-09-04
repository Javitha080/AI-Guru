"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  BookOpen,
  BookOpenCheck,
  Sparkles,
  Play,
  FileText,
  RefreshCw,
  ChevronRight,
  History,
  Cpu,
  Binary,
} from "lucide-react";
import { motionOK, useRevealStagger, useMagneticTilt } from "@/lib/motion/useGsapReveal";

const STUDENT_ID = "student-primary";
const cssVars = (o: Record<string, string>) => o as unknown as React.CSSProperties;

export interface RealStudyPreset {
  id: string;
  title: string;
  subject: string;
  duration: number;
  questionCount?: number;
  paperType?: string;
  grade?: number;
  paperNo?: number;
  medium?: string;
  isCustomExam?: boolean;
}

export interface PastSessionRow {
  id: string;
  title: string;
  subject: string;
  status: string;
  target_duration_seconds: number;
  actual_duration_seconds: number;
  focus_score: number;
  created_at: number;
}

export function RealPresetTile({
  preset,
  onPick,
}: {
  preset: RealStudyPreset;
  onPick: () => void;
}) {
  const tiltRef = useMagneticTilt<HTMLButtonElement>(motionOK() ? 4 : 0);
  const Icon = preset.isCustomExam
    ? FileText
    : preset.paperNo === 1
    ? BookOpenCheck
    : preset.grade === 11
    ? Cpu
    : Binary;

  return (
    <button
      ref={tiltRef}
      onClick={onPick}
      className="bento-cell bento-cell--hover tilt-glare p-4 text-left group outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] flex flex-col justify-between min-h-[145px] w-full"
    >
      <div>
        <div className="flex items-center justify-between mb-2.5">
          <span className="w-10 h-10 rounded-xl bg-[var(--ember-0)] border border-[var(--glass-border)] flex items-center justify-center text-[var(--primary)] transition-transform duration-300 ease-out group-hover:scale-110 group-hover:-rotate-6">
            <Icon size={19} />
          </span>
          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/30">
            {preset.subject}
          </span>
        </div>
        <h4
          className="text-xs font-bold leading-snug line-clamp-2 group-hover:text-[var(--primary)] transition-colors"
          title={preset.title}
        >
          {preset.title}
        </h4>
      </div>
      <div className="mt-3 pt-2 border-t border-[var(--glass-border)]/50 flex items-center justify-between text-[10px] text-[var(--muted-foreground)]">
        <span>{preset.duration} mins · Monitored</span>
        {preset.questionCount ? <span>{preset.questionCount}Q</span> : null}
      </div>
    </button>
  );
}

export default function IdleLobby({
  onStart,
  onResume,
  onCreate,
}: {
  onStart: (
    title: string,
    subject: string,
    duration: number,
    paperMeta?: { paperId?: string; bankPaperId?: string; grade?: number; isCustomExam?: boolean }
  ) => void;
  onResume: (row: PastSessionRow) => void;
  onCreate: () => void;
}) {
  const router = useRouter();
  const [recent, setRecent] = useState<PastSessionRow[] | null>(null);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [presets, setPresets] = useState<RealStudyPreset[] | null>(null);
  const [presetsLoading, setPresetsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/v1/study-session/history/${STUDENT_ID}?limit=5&offset=0`
        );
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (!cancelled) setRecent(Array.isArray(data.items) ? data.items : []);
      } catch {
        if (!cancelled) setHistoryFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setPresetsLoading(true);
      try {
        const [alRes, olRes, examRes] = await Promise.all([
          fetch("/api/v1/paper_bank/catalog?grade=13&medium=english&limit=4"),
          fetch("/api/v1/paper_bank/catalog?grade=11&medium=english&limit=4"),
          fetch("/api/v1/exams/list"),
        ]);

        const alData = alRes.ok ? await alRes.json() : { papers: [] };
        const olData = olRes.ok ? await olRes.json() : { papers: [] };
        const examsData = examRes.ok ? await examRes.json() : [];

        const alPapers: Array<{
          id: string;
          title: string;
          grade: number;
          paper_no: number;
          medium: string;
          question_count: number;
          default_duration_seconds: number;
        }> = Array.isArray(alData.papers) ? alData.papers : [];

        const olPapers: Array<{
          id: string;
          title: string;
          grade: number;
          paper_no: number;
          medium: string;
          question_count: number;
          default_duration_seconds: number;
        }> = Array.isArray(olData.papers) ? olData.papers : [];

        const customExams: Array<{
          id: string;
          title: string;
          status: string;
          question_count: number;
          mcq_duration_seconds: number;
        }> = Array.isArray(examsData) ? examsData : [];

        const items: RealStudyPreset[] = [];

        // 1. If custom uploaded exams exist, prioritize the most recent ready one
        const readyCustom = customExams.find((e) => e.status === "ready" || e.status === "created");
        if (readyCustom) {
          items.push({
            id: readyCustom.id,
            title: readyCustom.title,
            subject: "Custom Exam",
            duration: Math.max(15, Math.round((readyCustom.mcq_duration_seconds || 1800) / 60)),
            questionCount: readyCustom.question_count,
            paperType: "Uploaded Exam",
            isCustomExam: true,
          });
        }

        // 2. A/L Paper 1 (MCQ)
        const alP1 = alPapers.find((p) => p.paper_no === 1);
        if (alP1) {
          items.push({
            id: alP1.id,
            title: alP1.title,
            subject: "ICT (A/L)",
            duration: Math.round(alP1.default_duration_seconds / 60) || 45,
            questionCount: alP1.question_count,
            paperType: "Paper 1 (MCQ)",
            grade: alP1.grade,
            paperNo: alP1.paper_no,
            medium: alP1.medium,
          });
        }

        // 3. A/L Paper 2 (Structured)
        const alP2 = alPapers.find((p) => p.paper_no === 2);
        if (alP2) {
          items.push({
            id: alP2.id,
            title: alP2.title,
            subject: "ICT (A/L)",
            duration: Math.round(alP2.default_duration_seconds / 60) || 60,
            questionCount: alP2.question_count,
            paperType: "Paper 2 (Structured)",
            grade: alP2.grade,
            paperNo: alP2.paper_no,
            medium: alP2.medium,
          });
        }

        // 4. O/L Paper 1 (MCQ)
        const olP1 = olPapers.find((p) => p.paper_no === 1);
        if (olP1) {
          items.push({
            id: olP1.id,
            title: olP1.title,
            subject: "ICT (O/L)",
            duration: Math.round(olP1.default_duration_seconds / 60) || 40,
            questionCount: olP1.question_count,
            paperType: "Paper 1 (MCQ)",
            grade: olP1.grade,
            paperNo: olP1.paper_no,
            medium: olP1.medium,
          });
        }

        // 5. O/L Paper 2 (Structured) if room
        if (items.length < 4) {
          const olP2 = olPapers.find((p) => p.paper_no === 2);
          if (olP2) {
            items.push({
              id: olP2.id,
              title: olP2.title,
              subject: "ICT (O/L)",
              duration: Math.round(olP2.default_duration_seconds / 60) || 45,
              questionCount: olP2.question_count,
              paperType: "Paper 2 (Structured)",
              grade: olP2.grade,
              paperNo: olP2.paper_no,
              medium: olP2.medium,
            });
          }
        }

        // Fallback fill from alPapers if still under 4
        for (const p of alPapers) {
          if (items.length >= 4) break;
          if (!items.some((it) => it.id === p.id)) {
            items.push({
              id: p.id,
              title: p.title,
              subject: "ICT (A/L)",
              duration: Math.round(p.default_duration_seconds / 60) || 45,
              questionCount: p.question_count,
              paperType: `Paper ${p.paper_no}`,
              grade: p.grade,
              paperNo: p.paper_no,
              medium: p.medium,
            });
          }
        }

        if (!cancelled) {
          setPresets(items.slice(0, 4));
          setPresetsLoading(false);
        }
      } catch (err) {
        console.warn("Failed to load real presets:", err);
        if (!cancelled) {
          setPresets([]);
          setPresetsLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const resumeCandidate = recent?.find(
    (r) => r.status === "in_progress" || r.status === "paused"
  );

  const revealRoot = useRevealStagger<HTMLDivElement>([recent, presets]);

  return (
    <div className="flex-1 overflow-y-auto relative">
      {/* Drifting ember backdrop */}
      <div className="aurora-stage">
        <div
          className="aurora-blob"
          style={cssVars({ "--x": "16%", "--y": "-8%", "--size": "580px", "--drift-dur": "32s" })}
        />
        <div
          className="aurora-blob"
          style={cssVars({
            "--x": "90%",
            "--y": "106%",
            "--size": "470px",
            "--blob-color": "var(--amber-glow)",
            "--blob-opacity": "0.45",
            "--drift-dur": "38s",
            "--drift-delay": "-10s",
          })}
        />
      </div>

      <div ref={revealRoot} className="relative z-10 max-w-5xl mx-auto px-6 py-10 space-y-6">
        {/* Header row */}
        <div className="flex items-end justify-between gap-4" data-reveal>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-[var(--muted-foreground)]">
              AI Guru · Privacy-first
            </p>
            <h1 className="font-display text-4xl font-extrabold tracking-tight mt-1.5">
              Study{" "}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-[var(--primary)] to-[var(--amber)]">
                Room
              </span>
            </h1>
          </div>
          <button onClick={onCreate} className="glass-btn-primary hidden sm:inline-flex items-center gap-2 !rounded-xl">
            <Plus size={17} />
            <span>Custom Session</span>
          </button>
        </div>

        {/* Hero bento */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div
            data-reveal
            className="bento-cell tilt-glare liquid-sheen col-span-2 lg:row-span-2 p-6 lg:p-8 flex flex-col justify-between gap-5 min-h-[290px]"
          >
            <div className="space-y-3.5">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[var(--primary)]/25 to-[var(--amber)]/15 border border-[var(--ember-line)]/40 flex items-center justify-center text-[var(--primary)] shadow-[0_0_28px_var(--glow-primary)]">
                <BookOpen size={26} />
              </div>
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed max-w-sm">
                Intelligent, privacy-first study companion — local AI monitoring, PDF past-paper
                workspace, and real-time focus feedback. Nothing leaves your device.
              </p>
            </div>

            <div className="space-y-4">
              {/* Resumable session banner — real in-progress work first */}
              {resumeCandidate && (
                <div
                  className="p-3.5 rounded-xl bg-[var(--amber-glow)]/50 border border-[var(--amber)]/30 flex items-center justify-between gap-3 animate-fade-in"
                  role="status"
                >
                  <div className="text-left min-w-0">
                    <h4 className="text-xs font-bold text-[var(--amber)]">Unfinished session</h4>
                    <p className="text-[11px] text-[var(--muted-foreground)] mt-0.5 truncate">
                      {resumeCandidate.title}
                    </p>
                  </div>
                  <button
                    onClick={() => onResume(resumeCandidate)}
                    className="shrink-0 px-3.5 py-1.5 rounded-lg bg-[var(--amber)] text-black text-xs font-bold transition-transform hover:scale-105 active:scale-95 flex items-center gap-1.5"
                  >
                    <Play size={13} fill="currentColor" />
                    Resume
                  </button>
                </div>
              )}

              <button
                onClick={onCreate}
                className="glass-btn-primary sm:hidden w-full justify-center !rounded-xl"
              >
                <Plus size={17} />
                Custom Study Session
              </button>

              <button
                onClick={onCreate}
                className="group hidden sm:flex items-center gap-3 px-5 py-3.5 rounded-2xl bg-gradient-to-r from-[var(--primary)] to-[#E8895F] text-white font-bold shadow-[0_8px_30px_var(--glow-primary)] transition-all duration-300 hover:shadow-[0_10px_42px_var(--glow-primary)] hover:-translate-y-0.5 active:scale-[0.98] w-fit"
              >
                <Sparkles size={19} className="transition-transform duration-500 group-hover:rotate-12" />
                <span>Custom Study Session</span>
                <ChevronRight size={17} className="transition-transform duration-300 group-hover:translate-x-1 opacity-80" />
              </button>
            </div>
          </div>

          {/* Real past-paper preset tiles from Paper Bank & Exams */}
          {presetsLoading && (
            <>
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  data-reveal
                  className="bento-cell p-4 flex flex-col justify-between min-h-[145px] animate-pulse"
                >
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div className="w-10 h-10 rounded-xl bg-white/5" />
                      <div className="w-14 h-4 rounded-full bg-white/5" />
                    </div>
                    <div className="h-3.5 bg-white/10 rounded w-3/4 mb-2" />
                    <div className="h-3 bg-white/5 rounded w-1/2" />
                  </div>
                  <div className="h-3 bg-white/5 rounded w-2/3 mt-3" />
                </div>
              ))}
            </>
          )}

          {!presetsLoading && presets && presets.length > 0 && (
            presets.map((preset) => (
              <div key={preset.id} data-reveal>
                <RealPresetTile
                  preset={preset}
                  onPick={() =>
                    onStart(preset.title, preset.subject, preset.duration, {
                      bankPaperId: preset.isCustomExam ? undefined : preset.id,
                      paperId: preset.isCustomExam ? preset.id : undefined,
                      grade: preset.grade,
                      isCustomExam: preset.isCustomExam,
                    })
                  }
                />
              </div>
            ))
          )}

          {!presetsLoading && (!presets || presets.length === 0) && (
            <div data-reveal className="col-span-2 bento-cell p-5 flex flex-col items-center justify-center min-h-[145px] text-center text-xs text-[var(--muted-foreground)]">
              <FileText size={22} className="opacity-40 mb-2" />
              <p className="font-bold">No past papers available</p>
              <p className="text-[10px] opacity-75 mt-0.5">Use Custom Study Session to begin.</p>
            </div>
          )}

          {/* Recent sessions — real history from study_sessions */}
          <div data-reveal className="bento-cell col-span-2 lg:col-span-4 p-5">
            <h3 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)] flex items-center gap-1.5 mb-3">
              <History size={13} /> Recent Sessions
            </h3>

            {recent === null && !historyFailed && (
              <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)] py-2">
                <RefreshCw size={12} className="animate-spin" /> Loading…
              </div>
            )}

            {historyFailed && (
              <p className="text-xs text-[var(--muted-foreground)] py-2">
                History unavailable — backend offline.
              </p>
            )}

            {recent !== null && recent.length === 0 && !historyFailed && (
              <p className="text-xs text-[var(--muted-foreground)] py-2">
                No past sessions yet — your finished sessions appear here.
              </p>
            )}

            <div className="space-y-1.5">
              {recent?.map((r) => (
                <button
                  key={r.id}
                  onClick={() => router.push("/achievements")}
                  className="w-full text-left p-3 rounded-xl border border-transparent hover:border-[var(--glass-border)] hover:bg-[var(--ember-0)] transition-all duration-200 flex items-center justify-between gap-3 group"
                >
                  <div className="min-w-0 flex items-center gap-3">
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        r.status === "completed"
                          ? "bg-[var(--primary)]"
                          : r.status === "in_progress" || r.status === "paused"
                            ? "bg-[var(--amber)] ember-dot"
                            : "bg-[var(--muted-foreground)]/50"
                      }`}
                    />
                    <div className="min-w-0">
                      <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">
                        {r.title}
                      </p>
                      <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                        {new Date(r.created_at * 1000).toLocaleDateString()} ·{" "}
                        {r.status === "completed"
                          ? `${Math.round((r.actual_duration_seconds || 0) / 60)} min focused`
                          : r.status.replace(/_/g, " ")}
                      </p>
                    </div>
                  </div>
                  <ChevronRight
                    size={14}
                    className="shrink-0 text-[var(--muted-foreground)] transition-transform duration-300 group-hover:translate-x-1 group-hover:text-[var(--primary)]"
                  />
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
