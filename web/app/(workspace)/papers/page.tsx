"use client";

/**
 * AI Guru Paper Bank — LiquidGlass & Bento Grid edition.
 * Built-in A/L & O/L past papers, zero upload needed.
 * Subject -> grade -> medium -> year filters; start a sitting or resume one.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import {
  BookOpen, BookOpenCheck, ChevronRight, Clock, FileText, History,
  Languages, Loader2, Play, RefreshCw, ShieldCheck,
} from "lucide-react";
import SittingRunner from "@/components/papers/SittingRunner";
import { BentoGrid, BentoCard } from "@/components/ui/BentoGrid";
import { useScrollReveal } from "@/lib/motion/useScrollReveal";
import { useSmoothScroll } from "@/lib/motion/useSmoothScroll";
import {
  BankPaperDetail, CatalogRow, MySessionsResponse, papersApi, SittingState,
} from "@/lib/papers/paper-api";

const STUDENT_ID = "student-primary";

type CategoryFilter = "al" | "ol" | "topic" | "quiz";
type View =
  | { kind: "hub" }
  | { kind: "run"; sittingId: string; parts: Array<{ exam_id: string; bank_paper_id: string; paper_no: number; title: string }> };

function AuroraBackdrop() {
  const blobs: CSSProperties[] = [
    {
      "--x": "12%",
      "--y": "8%",
      "--size": "440px",
      "--blob-color": "var(--glow-primary)",
      "--blob-opacity": "0.50",
      "--drift-dur": "32s",
    } as CSSProperties,
    {
      "--x": "85%",
      "--y": "28%",
      "--size": "380px",
      "--blob-color": "var(--amber-glow)",
      "--blob-opacity": "0.38",
      "--drift-dur": "36s",
      "--drift-delay": "-8s",
    } as CSSProperties,
    {
      "--x": "40%",
      "--y": "80%",
      "--size": "500px",
      "--blob-color": "var(--ember-1)",
      "--blob-opacity": "0.30",
      "--drift-dur": "42s",
      "--drift-delay": "-16s",
    } as CSSProperties,
  ];

  return (
    <div className="aurora-stage" aria-hidden="true">
      {blobs.map((style, i) => (
        <span key={i} className="aurora-blob" style={style} />
      ))}
    </div>
  );
}

export default function PapersPage() {
  const [view, setView] = useState<View>({ kind: "hub" });

  return (
    <div className="flex-1 h-full min-h-0 flex flex-col text-[var(--foreground)] bg-[var(--background)]">
      {view.kind === "run" ? (
        <SittingRunner
          sittingId={view.sittingId}
          parts={view.parts}
          onExit={() => setView({ kind: "hub" })}
        />
      ) : (
        <Hub onStarted={(sittingId, parts) => setView({ kind: "run", sittingId, parts })} />
      )}
    </div>
  );
}

/* --------------------------------------------------------------------- hub */

function fmtDur(totalSeconds: number | null | undefined): string {
  const s = Math.max(0, Math.round(Number(totalSeconds) || 0));
  if (!s) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  return `${m}m`;
}

function Hub({ onStarted }: { onStarted: (sid: string, parts: Array<{ exam_id: string; bank_paper_id: string; paper_no: number; title: string }>) => void }) {
  const router = useRouter();
  const [category, setCategory] = useState<CategoryFilter>("al");
  const [medium, setMedium] = useState<string>("");
  const [rows, setRows] = useState<CatalogRow[] | null>(null);
  const [failed, setFailed] = useState(false);

  const scrollerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  useSmoothScroll(scrollerRef, contentRef);

  const [seeding, setSeeding] = useState(false);
  const seedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (seedTimer.current) {
      clearTimeout(seedTimer.current);
      seedTimer.current = null;
    }
    setRows(null); setFailed(false);
    try {
      let subject = "ict";
      let grade: number | undefined = 13;
      if (category === "ol") {
        subject = "ict-ol";
        grade = 11;
      } else if (category === "topic") {
        subject = "ict-topic";
        grade = undefined;
      } else if (category === "quiz") {
        subject = "ict-quiz";
        grade = undefined;
      }
      const res = await papersApi.catalog({ subject, grade });
      setRows(res.papers);
      if (res.seeding) {
        setSeeding(true);
        seedTimer.current = setTimeout(() => { void load(); }, 2000);
      } else {
        setSeeding(false);
      }
    } catch {
      setFailed(true);
    }
  }, [category]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => () => {
    if (seedTimer.current) clearTimeout(seedTimer.current);
  }, []);

  const syncArchive = useCallback(async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const res = await papersApi.syncMasterArchive();
      const skipped = (res.errors ?? []).length;
      setSyncMsg(
        `Synced ${res.imported_papers} papers (${res.total_questions} questions)` +
          (skipped ? ` · ${skipped} skipped` : "")
      );
    } catch (e) {
      setSyncMsg(e instanceof Error ? `Sync failed: ${e.message}` : "Sync failed");
    } finally {
      setSyncing(false);
      void load();
    }
  }, [load]);

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
      .sort((a, b) => (b[0].year ?? 0) - (a[0].year ?? 0) || a[0].title.localeCompare(b[0].title));
  }, [rows, medium]);

  useScrollReveal(scrollerRef, [rows, failed, groups.length]);

  const startSitting = (firstPaperId: string) => {
    // Timed exams run INSIDE a study-room session (same timer, same
    // monitoring WS) — never in this hub, which would split supervision.
    router.push(`/study-room?bankPaperId=${encodeURIComponent(firstPaperId)}&mode=timed`);
  };

  const openStudyPage = (paperId: string) => {
    // Study mode is a dedicated page: full paper + marking keys + AI tutor.
    router.push(`/papers/${encodeURIComponent(paperId)}`);
  };

  return (
    <div
      ref={scrollerRef}
      className="flex-1 h-full min-h-0 overflow-y-auto relative [scrollbar-gutter:stable]"
    >
      <AuroraBackdrop />

      <div ref={contentRef} className="relative z-10 max-w-5xl mx-auto px-6 py-10 space-y-7">
        <header className="space-y-2" data-scroll-reveal>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--ember-0)] border border-[var(--ember-line)]/30 text-[11px] font-bold uppercase tracking-[0.2em] text-[var(--primary)]">
            <ShieldCheck size={13} /> Built-in · offline · pre-keyed
          </div>
          <h1 className="font-display text-4xl font-extrabold tracking-tight mt-1">
            Paper{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-[var(--primary)] to-[var(--amber)]">
              Bank
            </span>
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] max-w-xl leading-relaxed">
            Real A/L &amp; O/L past papers with official answer keys and marking schemes.
            Paper 1 runs timed with instant grading, followed by structured essay breakdown.
          </p>
        </header>

        {/* Filters bar */}
        <div className="flex flex-wrap items-center gap-2.5 p-2 rounded-2xl surface-glass-base backdrop-blur-xl border border-[var(--glass-border)]" data-scroll-reveal>
          <div className="flex items-center gap-1.5 bg-black/20 p-1 rounded-xl">
            <GradeChip label="A/L Past Papers" active={category === "al"} onClick={() => setCategory("al")} />
            <GradeChip label="O/L Past Papers" active={category === "ol"} onClick={() => setCategory("ol")} />
            <GradeChip label="Topic Modules" active={category === "topic"} onClick={() => setCategory("topic")} />
            <GradeChip label="Daily Quizzes" active={category === "quiz"} onClick={() => setCategory("quiz")} />
          </div>

          <span className="w-px h-5 bg-[var(--glass-border)] mx-1" />

          <div className="flex items-center gap-1.5">
            <Languages size={14} className="text-[var(--muted-foreground)] ml-1 mr-0.5" />
            {[
              { key: "", label: "All" },
              { key: "english", label: "English" },
              { key: "sinhala", label: "සිංහල" },
            ].map(({ key, label }) => (
              <button
                key={key || "all"}
                onClick={() => setMedium(key)}
                className={`px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all duration-200 ${
                  medium === key
                    ? "bg-[var(--primary)] text-white border-transparent shadow-[0_2px_12px_var(--glow-primary)] scale-[1.02]"
                    : "bg-transparent border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-white/5"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <button
            onClick={() => void load()}
            className="ml-auto p-2 rounded-xl surface-glass-base glow-ring hover:text-[var(--primary)]"
            title="Refresh paper catalog"
            aria-label="Refresh paper catalog"
          >
            <RefreshCw size={14} className={rows === null && !failed ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => void syncArchive()}
            disabled={syncing}
            className="px-3 py-1.5 rounded-xl surface-glass-base glow-ring text-xs font-bold text-[var(--muted-foreground)] hover:text-[var(--primary)] disabled:opacity-50 flex items-center gap-1.5"
            title="Re-import the master archive (picks up new folders)"
          >
            {syncing ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            {syncing ? "Syncing…" : "Sync archive"}
          </button>
        </div>

        {rows !== null && !failed && (
          <p className="text-[11px] text-[var(--muted-foreground)] px-1" data-scroll-reveal>
            {rows.length} papers in {groups.length} groups (Paper 1 + Paper 2 paired per year)
            {medium ? ` · ${medium === "sinhala" ? "සිංහල" : "English"} only` : ""}
          </p>
        )}

        {syncMsg && (
          <div className="p-3 rounded-2xl border border-[var(--glass-border)] surface-glass-base text-xs text-[var(--muted-foreground)] backdrop-blur-md" data-scroll-reveal>
            {syncMsg}
          </div>
        )}

        {seeding && (
          <div className="p-4 rounded-2xl border border-[var(--primary)]/30 bg-[var(--ember-0)] text-xs text-[var(--primary)] flex items-center gap-2 backdrop-blur-md" data-scroll-reveal>
            <Loader2 size={15} className="animate-spin text-[var(--primary)]" />
            <span className="font-semibold">Setting up paper bank from archive… Initializing past papers in the background.</span>
          </div>
        )}

        {failed && (
          <div className="p-4 rounded-2xl border border-red-500/30 bg-red-500/10 text-xs text-red-300 backdrop-blur-md" data-scroll-reveal>
            Couldn&apos;t reach the paper bank. Make sure the AI Guru backend is running.
          </div>
        )}

        {/* Catalog */}
        {rows !== null && groups.length === 0 && !failed && (
          <div className="p-10 rounded-3xl border border-dashed border-[var(--glass-border-highlight)] text-center space-y-2 surface-glass-base" data-scroll-reveal>
            <BookOpenCheck size={26} className="mx-auto text-[var(--muted-foreground)] opacity-60" />
            <p className="text-sm font-semibold">No papers found for these filters</p>
            <p className="text-xs text-[var(--muted-foreground)]">Try switching between A/L and O/L or selecting All mediums.</p>
          </div>
        )}

        <BentoGrid gap="md">
          {groups.map((group) => {
            const head = group[0];
            const mcqPart = group.find((g) => g.paper_no === 1);
            const essayPart = group.find((g) => g.paper_no === 2);
            const targetId = mcqPart?.id ?? head.id;

            return (
              <BentoCard
                key={head.group_key}
                tier="liquid"
                span={6}
                tilt
                spotlight
                reveal
                interactive
                as="div"
                className="text-left w-full group relative overflow-hidden flex flex-col justify-between"
              >
                <div
                  className="cursor-pointer"
                  onClick={() => openStudyPage(targetId)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-display text-base font-bold group-hover:text-[var(--primary)] transition-colors">
                          ICT {head.year}
                        </span>
                        <span className="px-2 py-0.5 rounded-md text-[10px] font-extrabold uppercase tracking-wide bg-[var(--muted)] text-[var(--foreground)] border border-[var(--glass-border)]">
                          {head.grade === 11 ? "O/L" : "A/L"}
                        </span>
                      </div>
                      <p className="text-[12px] text-[var(--muted-foreground)] capitalize">
                        {head.medium === "sinhala" ? "සිංහල medium" : `${head.medium} medium`}
                      </p>
                    </div>
                    <div className="w-8 h-8 rounded-full surface-glass-base flex items-center justify-center text-[var(--muted-foreground)] group-hover:text-[var(--primary)] group-hover:scale-105 transition-all">
                      <ChevronRight size={16} className="transition-transform group-hover:translate-x-0.5" />
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-1.5 text-[11px] font-semibold">
                    {mcqPart && (
                      <span className="px-2.5 py-1 rounded-xl bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/30 flex items-center gap-1.5 shadow-sm">
                        <FileText size={12} /> P1 MCQ · {mcqPart.question_count}Q · <Clock size={12} /> {fmtDur(mcqPart.default_duration_seconds)}
                      </span>
                    )}
                    {essayPart && (
                      <span className="px-2.5 py-1 rounded-xl surface-glass-base text-[var(--muted-foreground)] border border-[var(--glass-border)] flex items-center gap-1.5">
                        P2 Essay · {essayPart.question_count}Q · <Clock size={12} /> {fmtDur(essayPart.default_duration_seconds)}
                      </span>
                    )}
                    {mcqPart?.has_scheme_keys && essayPart?.has_scheme_keys ? (
                      <span className="px-2.5 py-1 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 flex items-center gap-1">
                        Keys Included
                      </span>
                    ) : mcqPart?.has_scheme_keys ? (
                      <span className="px-2.5 py-1 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 flex items-center gap-1">
                        P1 Keys · P2 AI-graded
                      </span>
                    ) : (
                      <span className="px-2.5 py-1 rounded-xl bg-sky-500/10 text-sky-300 border border-sky-500/25 flex items-center gap-1">
                        AI-graded · No official key
                      </span>
                    )}
                  </div>
                </div>

                <div className="mt-4 pt-3 border-t border-[var(--glass-border)] flex items-center gap-2">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      openStudyPage(targetId);
                    }}
                    className="flex-1 py-2 px-3 rounded-xl surface-glass-base border border-[var(--glass-border)] text-xs font-semibold text-[var(--foreground)] hover:text-[var(--primary)] hover:border-[var(--ember-line)] transition-all flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <BookOpen size={13} />
                    <span>Study Paper</span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      startSitting(targetId);
                    }}
                    title="Open in the Study Room — same timer, same monitoring"
                    className="flex-1 py-2 px-3 rounded-xl bg-[var(--primary)] text-white text-xs font-bold shadow-[0_2px_10px_var(--glow-primary)] hover:opacity-95 disabled:opacity-50 transition-all flex items-center justify-center gap-1.5"
                  >
                    <Play size={13} className="fill-current" />
                    <span>Timed Exam</span>
                  </button>
                </div>
              </BentoCard>
            );
          })}
        </BentoGrid>

        <MySessions onOpen={(sid, parts) => onStarted(sid, parts)} />
      </div>
    </div>
  );
}

function GradeChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ${
        active
          ? "bg-[var(--primary)] text-white shadow-[0_2px_12px_var(--glow-primary)] scale-[1.03]"
          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
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
    <section className="space-y-3 pt-4" data-scroll-reveal>
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-[0.18em] text-[var(--muted-foreground)] flex items-center gap-1.5">
          <History size={13} /> Your Sittings
        </h3>
        {data && (
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {unfinished.length} in progress · {finished.length} completed
          </span>
        )}
      </div>

      {failed && (
        <p className="text-xs text-[var(--muted-foreground)] p-3 rounded-xl surface-glass-base">
          Session history unavailable.
        </p>
      )}

      {!failed && data && unfinished.length === 0 && finished.length === 0 && (
        <div className="p-6 rounded-2xl surface-glass-base text-center text-xs text-[var(--muted-foreground)]">
          No sittings yet — pick a paper above to begin your first test.
        </div>
      )}

      {/* Unfinished active sessions */}
      <div className="grid gap-3 md:grid-cols-2">
        {unfinished.map((s) => (
          <button
            key={s.sitting_id}
            onClick={() => void openSitting(s.sitting_id)}
            disabled={resumingId !== ""}
            className="w-full text-left p-4 rounded-2xl bg-[var(--amber-glow)]/30 border border-[var(--amber)]/40 hover:border-[var(--amber)] transition-all duration-200 flex items-center justify-between gap-3 group backdrop-blur-xl shadow-lg shadow-black/20"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[var(--amber)] animate-pulse" />
                <p className="text-xs font-bold text-[var(--amber)] truncate">
                  {s.parts[0]?.title ?? "Sitting"}
                </p>
              </div>
              <p className="text-[11px] text-[var(--muted-foreground)] mt-1 font-mono">
                {s.parts.map((p) => `P${p.paper_no}: ${p.status}`).join(" · ")}
              </p>
            </div>
            <span className="shrink-0 px-3 py-1.5 rounded-xl bg-[var(--amber)] text-black text-xs font-bold flex items-center gap-1.5 shadow-md shadow-amber-500/20 group-hover:scale-105 transition-transform">
              <Play size={12} fill="currentColor" /> Resume
            </span>
          </button>
        ))}
      </div>

      {/* Finished graded sessions */}
      <div className="grid gap-2.5 md:grid-cols-2">
        {finished.slice(0, 6).map((s) => {
          const total = s.parts.reduce((acc, p) => acc + (p.awarded || 0), 0);
          const marks = s.parts.reduce((acc, p) => acc + (p.max_marks || 0), 0);
          const pct = marks > 0 ? Math.round((total / marks) * 100) : null;
          return (
            <button
              key={s.sitting_id}
              onClick={() => void openSitting(s.sitting_id)}
              disabled={resumingId !== ""}
              className="w-full text-left p-3.5 rounded-2xl surface-glass-base hover:border-[var(--ember-line)]/50 transition-all duration-200 flex items-center justify-between gap-3 group"
            >
              <div className="min-w-0">
                <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">
                  {s.parts[0]?.title}
                </p>
                <p className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
                  {s.parts.length} part{s.parts.length > 1 ? "s" : ""} · {marks} marks total
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded-md ${
                  pct !== null && pct >= 50
                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                    : "bg-red-500/10 text-red-400 border border-red-500/20"
                }`}>
                  {pct !== null ? `${pct}%` : "—"}
                </span>
                <ChevronRight size={14} className="text-[var(--muted-foreground)] group-hover:translate-x-0.5 transition-transform" />
              </div>
            </button>
          );
        })}
      </div>

      {resumeErr && <p className="text-xs text-red-400 p-2">{resumeErr}</p>}
    </section>
  );
}

