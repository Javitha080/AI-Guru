"use client";

/**
 * AI Guru Paper Bank — built-in A/L & O/L past papers, zero upload needed.
 * Subject → grade → medium → year filters; start a sitting or resume one.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpenCheck, ChevronRight, Clock, FileText, History,
  Languages, Loader2, Play, RefreshCw, ShieldCheck,
} from "lucide-react";
import SittingRunner from "@/components/papers/SittingRunner";
import {
  BankPaperDetail, CatalogRow, MySessionsResponse, papersApi, SittingState,
} from "@/lib/papers/paper-api";

const STUDENT_ID = "student-primary";

type GradeFilter = 11 | 12 | 13;
type View =
  | { kind: "hub" }
  | { kind: "run"; sittingId: string; parts: Array<{ exam_id: string; bank_paper_id: string; paper_no: number; title: string }> };

export default function PapersPage() {
  const [view, setView] = useState<View>({ kind: "hub" });

  if (view.kind === "run") {
    return (
      <div className="flex-1 h-full flex flex-col text-[var(--foreground)]">
        <SittingRunner
          sittingId={view.sittingId}
          parts={view.parts}
          onExit={() => setView({ kind: "hub" })}
        />
      </div>
    );
  }
  return <Hub onStarted={(sittingId, parts) => setView({ kind: "run", sittingId, parts })} />;
}

/* --------------------------------------------------------------------- hub */

function Hub({ onStarted }: { onStarted: (sid: string, parts: Array<{ exam_id: string; bank_paper_id: string; paper_no: number; title: string }>) => void }) {
  const [grade, setGrade] = useState<GradeFilter>(13);
  const [medium, setMedium] = useState<string>("");
  const [rows, setRows] = useState<CatalogRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [startingId, setStartingId] = useState("");
  const [startError, setStartError] = useState("");

  const load = useCallback(async () => {
    setRows(null); setFailed(false);
    try {
      const res = await papersApi.catalog({ subject: grade === 11 ? "ict-ol" : "ict", grade });
      setRows(res.papers);
    } catch {
      setFailed(true);
    }
  }, [grade]);

  useEffect(() => { void load(); }, [load]);

  const groups = useMemo(() => {
    const filtered = (rows ?? []).filter((r) => !medium || r.medium === medium);
    const map = new Map<string, CatalogRow[]>();
    for (const r of filtered) {
      const list = map.get(r.group_key) ?? [];
      list.push(r);
      map.set(r.group_key, list);
    }
    return [...map.values()]
      .map((list) => list.sort((a, b) => a.paper_no - b.paper_no))
      .sort((a, b) => (b[0].year ?? 0) - (a[0].year ?? 0));
  }, [rows, medium]);

  const startSitting = async (firstPaperId: string) => {
    setStartingId(firstPaperId); setStartError("");
    try {
      const started = await papersApi.start(firstPaperId, STUDENT_ID);
      onStarted(
        started.sitting_id,
        started.parts.map((p) => ({
          exam_id: p.exam_id, bank_paper_id: p.bank_paper_id,
          paper_no: p.paper_no, title: p.title,
        }))
      );
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e));
    } finally {
      setStartingId("");
    }
  };

  return (
    <div className="flex-1 overflow-y-auto relative">
      <div className="relative z-10 max-w-5xl mx-auto px-6 py-10 space-y-6">
        <header className="space-y-1.5" data-reveal>
          <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-[var(--muted-foreground)] flex items-center gap-1.5">
            <ShieldCheck size={12} /> Built-in · offline · pre-keyed
          </p>
          <h1 className="font-display text-4xl font-extrabold tracking-tight mt-1.5">
            Paper{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-[var(--primary)] to-[var(--amber)]">Bank</span>
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] max-w-xl">
            Real A/L past papers with official answer keys and marking notes. Pick a year —
            Paper 1 runs 2 hours timed, then the double-check window opens before Paper 2.
          </p>
        </header>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2">
          <GradeChip label="O/L · Grade 11" active={grade === 11} onClick={() => setGrade(11)} />
          <GradeChip label="A/L · Grade 12" active={grade === 12} onClick={() => setGrade(12)} />
          <GradeChip label="A/L · Grade 13" active={grade === 13} onClick={() => setGrade(13)} />
          <span className="w-px h-5 bg-[var(--glass-border)] mx-1" />
          <Languages size={14} className="text-[var(--muted-foreground)]" />
          {["", "english", "sinhala"].map((m) => (
            <button key={m || "all"} onClick={() => setMedium(m)}
              className={`px-3 py-1.5 rounded-full text-xs font-bold border transition-colors ${
                medium === m ? "bg-[var(--primary)] text-white border-transparent"
                : "surface-glass-base border-[var(--glass-border)] hover:border-[var(--ember-line)]"
              }`}>
              {m === "" ? "All" : m === "english" ? "English" : "සිංහල"}
            </button>
          ))}
          <button onClick={() => void load()} className="ml-auto p-2 rounded-lg surface-glass-base glow-ring" title="Refresh">
            <RefreshCw size={14} className={rows === null && !failed ? "animate-spin" : ""} />
          </button>
        </div>

        {failed && (
          <div className="p-4 rounded-xl border border-red-500/30 bg-red-500/10 text-xs text-red-300">
            Couldn&apos;t reach the paper bank. Make sure the AI Guru backend is running.
          </div>
        )}

        {/* Catalog */}
        {rows !== null && groups.length === 0 && !failed && (
          <div className="p-8 rounded-2xl border border-dashed border-[var(--glass-border-highlight)] text-center space-y-1.5">
            <BookOpenCheck size={22} className="mx-auto text-[var(--muted-foreground)]" />
            <p className="text-sm font-semibold">No papers here yet</p>
            <p className="text-xs text-[var(--muted-foreground)]">Try another grade or medium filter.</p>
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-2">
          {groups.map((group) => {
            const head = group[0];
            const mcqPart = group.find((g) => g.paper_no === 1);
            const essayPart = group.find((g) => g.paper_no === 2);
            return (
              <button key={head.group_key}
                onClick={() => void startSitting(mcqPart?.id ?? head.id)}
                disabled={startingId !== ""}
                className="bento-cell bento-cell--hover tilt-glare p-4 text-left group disabled:opacity-60 relative overflow-hidden">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <h3 className="text-sm font-bold group-hover:text-[var(--primary)] transition-colors">
                      ICT {head.year} · Grade {head.grade}
                    </h3>
                    <p className="text-[11px] text-[var(--muted-foreground)] capitalize">
                      {head.medium === "sinhala" ? "සිංහල medium" : `${head.medium} medium`}
                    </p>
                  </div>
                  <ChevronRight size={16} className="shrink-0 text-[var(--muted-foreground)] transition-transform group-hover:translate-x-1 group-hover:text-[var(--primary)]" />
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5 text-[10px] font-semibold">
                  {mcqPart && (
                    <span className="px-2 py-0.5 rounded-full bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/30 flex items-center gap-1">
                      <FileText size={10} /> P1 MCQ · {mcqPart.question_count}Q · <Clock size={10} /> 2h
                    </span>
                  )}
                  {essayPart && (
                    <span className="px-2 py-0.5 rounded-full surface-glass-base text-[var(--muted-foreground)] border border-[var(--glass-border)] flex items-center gap-1">
                      P2 Essay · {essayPart.question_count}Q · <Clock size={10} /> 3h
                    </span>
                  )}
                  <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/25">
                    Answer keys ✓
                  </span>
                </div>
                {startingId === (mcqPart?.id ?? head.id) && (
                  <span className="absolute inset-0 bg-black/40 backdrop-blur-[2px] flex items-center justify-center text-xs font-bold gap-2">
                    <Loader2 size={14} className="animate-spin" /> Starting…
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {startError && (
          <p className="text-xs text-red-400">{startError}</p>
        )}

        <MySessions onOpen={(sid, parts) => onStarted(sid, parts)} />
      </div>
    </div>
  );
}

function GradeChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`px-3.5 py-1.5 rounded-full text-xs font-bold border transition-colors ${
        active ? "bg-[var(--primary)] text-white border-transparent shadow-[0_4px_16px_var(--glow-primary)]"
        : "surface-glass-base border-[var(--glass-border)] hover:border-[var(--ember-line)]"
      }`}>
      {label}
    </button>
  );
}

/* ------------------------------------------------------------- my sittings */

function MySessions({ onOpen }: { onOpen: (sid: string, parts: Array<{ exam_id: string; bank_paper_id: string; paper_no: number; title: string }>) => void }) {
  const [data, setData] = useState<MySessionsResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [resumingId, setResumingId] = useState("");
  const [resumeErr, setResumeErr] = useState("");

  const refresh = useCallback(() => {
    setFailed(false);
    papersApi.mySessions(STUDENT_ID).then(setData).catch(() => setFailed(true));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  /** Rebuild runner parts for a sitting from live server state. */
  const openSitting = async (sittingId: string) => {
    setResumingId(sittingId); setResumeErr("");
    try {
      const st: SittingState = await papersApi.state(sittingId);
      const parts = [];
      for (const p of st.parts) {
        if (!p.bank_paper_id) continue;
        const detail: BankPaperDetail = await papersApi.getPaper(p.bank_paper_id);
        parts.push({
          exam_id: p.exam_id, bank_paper_id: p.bank_paper_id,
          paper_no: p.paper_no, title: detail.paper.title,
        });
      }
      if (!parts.length) throw new Error("This sitting has no resumable parts.");
      onOpen(sittingId, parts);
    } catch (e) {
      setResumeErr(e instanceof Error ? e.message : String(e));
    } finally {
      setResumingId("");
    }
  };

  const unfinished = (data?.sittings ?? []).filter((s) =>
    s.parts.some((p) => p.status === "active" || p.status === "review")
  );
  const finished = (data?.sittings ?? []).filter((s) =>
    s.parts.every((p) => p.status === "graded") && s.parts.length > 0
  );

  return (
    <section className="space-y-2 pt-2">
      <h3 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)] flex items-center gap-1.5">
        <History size={13} /> Your Sittings
      </h3>

      {failed && <p className="text-xs text-[var(--muted-foreground)]">Session history unavailable.</p>}
      {!failed && data && unfinished.length === 0 && finished.length === 0 && (
        <p className="text-xs text-[var(--muted-foreground)] py-1">No sittings yet — pick a paper above to begin.</p>
      )}

      {unfinished.map((s) => (
        <button key={s.sitting_id} onClick={() => void openSitting(s.sitting_id)}
          disabled={resumingId !== ""}
          className="w-full text-left p-3.5 rounded-xl bg-[var(--amber-glow)]/50 border border-[var(--amber)]/30 flex items-center justify-between gap-3 group">
          <div className="min-w-0">
            <p className="text-xs font-bold text-[var(--amber)] truncate">
              {s.parts[0]?.title ?? "Sitting"} — in progress
            </p>
            <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
              {s.parts.map((p) => `P${p.paper_no}: ${p.status}`).join(" · ")}
            </p>
          </div>
          <span className="shrink-0 px-3.5 py-1.5 rounded-lg bg-[var(--amber)] text-black text-xs font-bold flex items-center gap-1.5">
            <Play size={12} fill="currentColor" /> Resume
          </span>
        </button>
      ))}

      {finished.slice(0, 6).map((s) => {
        const total = s.parts.reduce((acc, p) => acc + (p.awarded || 0), 0);
        const marks = s.parts.reduce((acc, p) => acc + (p.max_marks || 0), 0);
        const pct = marks > 0 ? Math.round((total / marks) * 100) : null;
        return (
          <button key={s.sitting_id} onClick={() => void openSitting(s.sitting_id)}
            disabled={resumingId !== ""}
            className="w-full text-left p-3 rounded-xl surface-glass-base hover:border-[var(--ember-line)]/50 transition-all duration-200 flex items-center justify-between gap-3 group">
            <div className="min-w-0">
              <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">{s.parts[0]?.title}</p>
              <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                {s.parts.length} part{s.parts.length > 1 ? "s" : ""} · {marks} marks
              </p>
            </div>
            <span className={`text-xs font-mono font-bold shrink-0 ${pct !== null && pct >= 50 ? "text-emerald-400" : "text-red-400"}`}>
              {pct !== null ? `${pct}%` : "—"}
            </span>
          </button>
        );
      })}

      {resumeErr && <p className="text-xs text-red-400">{resumeErr}</p>}
    </section>
  );
}
