"use client";

import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  BookOpenCheck,
  Play,
  FileText,
  RefreshCw,
  ChevronRight,
  ChevronLeft,
  Loader2,
} from "lucide-react";
import { apiFetch, apiUrl } from "@/lib/api";
import SittingRunner from "@/components/papers/SittingRunner";
import { papersApi } from "@/lib/papers/paper-api";

const STUDENT_ID = "student-primary";
const cssVars = (o: Record<string, string>) => o as unknown as React.CSSProperties;

interface BankPaperRow {
  id: string;
  group_key: string;
  paper_no: number;
  grade: number;
  subject: string;
  year: number;
  medium: string;
  title: string;
  question_count: number;
  mcq_count: number;
  essay_count: number;
  total_marks: number;
  default_duration_seconds: number;
}

type LevelFilter = "All" | "O/L" | "A/L";

/** Client-side level mapping (one merged fetch covers every level). */
function levelOfPaper(p: Pick<BankPaperRow, "subject" | "grade">): "O/L" | "A/L" | "other" {
  if (p.subject === "ict-ol" || p.grade === 10 || p.grade === 11) return "O/L";
  if (p.subject === "ict" || p.grade === 12 || p.grade === 13) return "A/L";
  return "other";
}

const BANK_SUBJECTS = ["ict", "ict-ol", "ict-topic", "ict-quiz"];
const PAGE_SIZE = 24;

export interface PastPaperPanelProps {
  subject: string;
  initialPaperId?: string;
  initialGrade?: number;
  /**
   * Paper-Bank deep-link ("Timed Exam"): auto-start this paper's sitting
   * once the catalog loads, inside the running study session.
   */
  autoStartPaperId?: string | null;
  /**
   * Fired when a paper sitting starts inline: the room adopts the paper's
   * own duration as the session target so the countdown matches the work.
   */
  onPaperStart?: (info: { durationSeconds: number; title: string }) => void;
}

/**
 * Real past-paper workspace: Paper Bank built-in past papers (English & Sinhala)
 * + uploaded custom exam papers with 1-click start under study telemetry.
 */
export default function PastPaperPanel({
  subject,
  initialPaperId,
  initialGrade,
  autoStartPaperId,
  onPaperStart,
}: PastPaperPanelProps) {
  type Level = LevelFilter;
  // Levels only: O/L covers grades 10–11, A/L covers 12–13. No per-grade
  // split — one merged fetch returns every level; filtering is client-side
  // so "All" honestly shows the whole bank.
  const levelFromProps: Level =
    initialGrade === 10 || initialGrade === 11
      ? "O/L"
      : initialGrade === 12 || initialGrade === 13
        ? "A/L"
        : /o\/l/i.test(subject)
          ? "O/L"
          : "A/L";
  const [level, setLevel] = useState<Level>(levelFromProps);
  const [bankMedium, setBankMedium] = useState<string>("");
  const [bankQuery, setBankQuery] = useState<string>("");
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);
  const [bankPapers, setBankPapers] = useState<BankPaperRow[] | null>(null);
  const [uploadedPapers, setUploadedPapers] = useState<
    Array<{
      id: string;
      exam_id?: string;
      title: string;
      status: string;
      total_marks: number;
      question_count: number;
      created_at?: number | null;
    }> | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  // Inline sitting: the paper runs INSIDE the study room (same timer, same
  // monitoring WS) instead of a new tab that would kill both.
  const [activeSitting, setActiveSitting] = useState<{
    sittingId: string;
    parts: Array<{ exam_id: string; bank_paper_id: string; paper_no: number; title: string }>;
  } | null>(null);
  const [startingId, setStartingId] = useState("");
  const [startError, setStartError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      // One merged fetch across every bank subject — the old per-level
      // query hid half the bank behind the O/L↔A/L toggle.
      const bankReqs = BANK_SUBJECTS.map((s) =>
        apiFetch(apiUrl(`/api/v1/paper_bank/catalog?subject=${s}`))
      );
      const [bankRess, examRes] = await Promise.all([
        Promise.all(bankReqs),
        // only_uploads=true: Paper-Bank sittings belong under "Your Sittings"
        // in the Paper Bank, never under "Your Uploaded Papers".
        apiFetch(apiUrl("/api/v1/exams/list?only_uploads=true&limit=20")),
      ]);
      const merged: BankPaperRow[] = [];
      const seen = new Set<string>();
      let anyBankOk = false;
      for (const bankRes of bankRess) {
        if (!bankRes.ok) continue;
        anyBankOk = true;
        const bData = await bankRes.json();
        for (const p of bData.papers || []) {
          if (p?.id && !seen.has(p.id)) {
            seen.add(p.id);
            merged.push(p);
          }
        }
      }
      // Newest first so the full bank reads chronologically.
      merged.sort((a, b) => (b.year ?? 0) - (a.year ?? 0) || a.title.localeCompare(b.title));
      setBankPapers(anyBankOk ? merged : []);
      if (examRes.ok) {
        const eData = await examRes.json();
        const raw: Array<Record<string, unknown>> = Array.isArray(eData) ? eData : [];
        // Honest client-side gate: drop test-harness rows and empty
        // extractions that can never render as a real paper.
        const cleaned = raw
          .map((r) => ({
            id: String(r.id ?? r.exam_id ?? ""),
            title: String(r.title ?? "Untitled paper"),
            status: String(r.status ?? "ready"),
            total_marks: Number(r.total_marks ?? 0),
            question_count: Number(r.question_count ?? 0),
            created_at:
              typeof r.created_at === "number" ? (r.created_at as number) : null,
          }))
          .filter((p) => p.id && !p.id.startsWith("test-exam-") && p.question_count > 0);
        setUploadedPapers(cleaned);
      } else {
        setUploadedPapers([]);
      }
      if (!anyBankOk && !examRes.ok) setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const lv: Level =
      initialGrade === 10 || initialGrade === 11
        ? "O/L"
        : initialGrade === 12 || initialGrade === 13
          ? "A/L"
          : /o\/l/i.test(subject)
            ? "O/L"
            : "A/L";
    setLevel((prev) => (prev === lv ? prev : lv));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subject, initialGrade]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredBank = useMemo(() => {
    if (!bankPapers) return [];
    const q = bankQuery.trim().toLowerCase();
    return bankPapers.filter((p) => {
      if (level !== "All") {
        const lv = levelOfPaper(p);
        if (lv !== level && !(level === "A/L" && lv === "other")) return false;
      }
      if (bankMedium && p.medium !== bankMedium) return false;
      if (q && !`${p.title} ${p.year} ${p.subject}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [bankPapers, level, bankMedium, bankQuery]);

  // New arrivals reset the paging window so filters never strand the user
  // on an empty page.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [level, bankMedium, bankQuery]);

  const selectedPaper = useMemo(() => {
    if (!initialPaperId || !bankPapers) return null;
    return bankPapers.find((p) => p.id === initialPaperId) || null;
  }, [initialPaperId, bankPapers]);

  const openPreservingSession = (url: string) => {
    // The full Paper Bank hub lives outside the room: navigating away would
    // kill the live timer + monitoring WS, so only the hub link opens aside.
    window.open(url, "_blank", "noopener");
  };

  const startPaperInline = useCallback(
    async (paperId: string, fallbackSecs: number, title: string) => {
      setStartingId(paperId);
      setStartError("");
      try {
        const started = await papersApi.start(paperId, STUDENT_ID);
        setActiveSitting({
          sittingId: started.sitting_id,
          parts: started.parts.map((p) => ({
            exam_id: p.exam_id,
            bank_paper_id: p.bank_paper_id,
            paper_no: p.paper_no,
            title: p.title,
          })),
        });
        // Adopt the paper's own clock: server parts carry per-part durations;
        // fall back to the catalog default when the server omits them.
        const serverTotal = started.parts.reduce(
          (acc, p) => acc + (Number(p.duration_seconds) || 0),
          0
        );
        const total = serverTotal > 0 ? serverTotal : Math.max(60, Math.round(fallbackSecs));
        onPaperStart?.({ durationSeconds: total, title: started.title || title });
      } catch (e) {
        setStartError(e instanceof Error ? e.message : String(e));
      } finally {
        setStartingId("");
      }
    },
    [onPaperStart]
  );

  // Paper-Bank deep-link auto-start: fire once per paper id when the merged
  // catalog arrives. Back-to-papers never re-fires (consumed ref).
  const autoStartedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!autoStartPaperId || !bankPapers || activeSitting || startingId !== "") return;
    if (autoStartedRef.current === autoStartPaperId) return;
    const target = bankPapers.find((p) => p.id === autoStartPaperId);
    if (!target) return;
    autoStartedRef.current = autoStartPaperId;
    void startPaperInline(target.id, target.default_duration_seconds || 3600, target.title);
  }, [autoStartPaperId, bankPapers, activeSitting, startingId, startPaperInline]);

  if (activeSitting) {
    return (
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <div className="px-5 pt-3 shrink-0">
          <button
            onClick={() => setActiveSitting(null)}
            className="inline-flex items-center gap-1.5 text-[11px] font-bold text-[var(--muted-foreground)] hover:text-[var(--primary)] transition-colors"
          >
            <ChevronLeft size={14} />
            <span>Back to papers (timer + monitoring keep running)</span>
          </button>
        </div>
        <SittingRunner
          sittingId={activeSitting.sittingId}
          parts={activeSitting.parts}
          onExit={() => setActiveSitting(null)}
        />
      </div>
    );
  }

  return (
    <div className="flex-1 p-5 pt-4 overflow-y-auto space-y-4 print:overflow-visible print:p-0 print:space-y-2 print:bg-white print:text-black">
      {/* Target paper prompt if started from a specific preset */}
      {selectedPaper && (
        <div className="bento-cell liquid-sheen p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 border border-[var(--primary)]/40 bg-[var(--ember-0)]/60 animate-fade-in shadow-[0_4px_24px_var(--glow-primary)]">
          <div className="space-y-1 min-w-0">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--primary)] flex items-center gap-1.5">
              <BookOpenCheck size={13} /> Active Target Paper
            </span>
            <h4 className="text-xs sm:text-sm font-bold truncate">
              {selectedPaper.title}
            </h4>
            <p className="text-[10px] text-[var(--muted-foreground)]">
              {selectedPaper.question_count} Questions · {selectedPaper.total_marks} Marks ·{" "}
              {selectedPaper.medium === "sinhala" ? "සිංහල" : "English"} Medium
            </p>
          </div>
          <button
            onClick={() =>
              void startPaperInline(
                selectedPaper.id,
                selectedPaper.default_duration_seconds || 3600,
                selectedPaper.title
              )
            }
            disabled={startingId !== ""}
            className="shrink-0 px-3.5 py-1.5 rounded-xl bg-[var(--primary)] text-white text-xs font-bold transition-all hover:brightness-110 hover:-translate-y-0.5 active:scale-95 shadow-[0_4px_16px_var(--glow-primary)] flex items-center gap-1.5 disabled:opacity-50"
          >
            {startingId === selectedPaper.id ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Play size={13} fill="currentColor" />
            )}
            Start Here — Timer Follows Paper
          </button>
        </div>
      )}

      {/* Exam Room hero strip */}
      <div className="bento-cell liquid-sheen p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 overflow-hidden relative">
        <div className="aurora-stage !absolute">
          <div
            className="aurora-blob"
            style={cssVars({
              "--x": "85%",
              "--y": "0%",
              "--size": "320px",
              "--blob-opacity": "0.5",
            })}
          />
        </div>
        <div className="space-y-1.5 relative z-10">
          <h3 className="text-sm font-bold flex items-center gap-2">
            <BookOpenCheck size={15} className="text-[var(--primary)]" />
            Paper Bank — Official A/L &amp; O/L Papers
          </h3>
          <p className="text-[11px] text-[var(--muted-foreground)] leading-relaxed max-w-md">
            Built-in English &amp; Sinhala medium papers with official answer keys:
            timed Paper 1 (MCQ) and Paper 2 (Structured Essay) with AI grading.
            {!/ict|computer/i.test(subject) && (
              <span className="block mt-1 opacity-80">
                Note: the bank currently hosts ICT papers — your {subject} session timer,
                monitoring and notes still run normally.
              </span>
            )}
          </p>
        </div>
        <button
          onClick={() => openPreservingSession("/papers")}
          className="shrink-0 relative z-10 px-4 py-2 rounded-xl bg-[var(--primary)] text-white text-xs font-bold transition-all hover:brightness-110 hover:-translate-y-0.5 active:scale-95 shadow-[0_6px_20px_var(--glow-primary)]"
        >
          Open Full Paper Bank
        </button>
      </div>

      {/* Floating Guru hint */}
      <div className="bento-cell p-4 flex items-center justify-between gap-3">
        <div>
          <h4 className="text-xs font-bold text-[var(--amber)]">Need a Step Hint?</h4>
          <p className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
            Studying {subject} — ask AI Guru without leaving your workspace.
          </p>
        </div>
        <button
          onClick={() =>
            window.dispatchEvent(
              new CustomEvent("aiguru:open-floating-chat", {
                detail: {
                  context: `I'm in the Study Room working on ${subject} past papers. I need a hint.`,
                },
              })
            )
          }
          className="shrink-0 px-3.5 py-1.5 rounded-lg surface-glass-base glow-ring text-xs font-bold text-[var(--primary)] transition-colors"
        >
          Ask AI Guru
        </button>
      </div>

      {/* Quick Filters */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)] flex items-center gap-1.5">
            <FileText size={13} /> Built-in Past Papers
            {bankPapers !== null && (
              <span className="normal-case font-semibold opacity-70">
                ({filteredBank.length}{bankPapers.length !== filteredBank.length ? ` of ${bankPapers.length}` : ""})
              </span>
            )}
          </h4>
          <div className="flex items-center gap-1 flex-wrap justify-end">
            {(["All", "O/L", "A/L"] as const).map((lv) => (
              <button
                key={lv}
                onClick={() => setLevel(lv)}
                aria-pressed={level === lv}
                title={lv === "All" ? "Every paper in the bank" : lv === "O/L" ? "Ordinary Level (Grades 10–11)" : "Advanced Level (Grades 12–13)"}
                className={`px-3 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                  level === lv
                    ? "bg-[var(--primary)] text-white border-transparent"
                    : "surface-glass-base border-[var(--glass-border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {lv}
              </button>
            ))}
            <span className="w-px h-4 bg-[var(--glass-border)] mx-0.5" aria-hidden />
            {["", "english", "sinhala"].map((m) => (
              <button
                key={m || "all"}
                onClick={() => setBankMedium(m)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                  bankMedium === m
                    ? "bg-[var(--primary)] text-white border-transparent"
                    : "surface-glass-base border-[var(--glass-border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {m === "" ? "All" : m === "english" ? "EN" : "සිංහල"}
              </button>
            ))}
          </div>
        </div>

        <div className="relative">
          <input
            value={bankQuery}
            onChange={(e) => setBankQuery(e.target.value)}
            placeholder="Search papers by title or year…"
            aria-label="Search built-in past papers"
            className="glass-input w-full px-3.5 py-2 text-xs"
          />
          {bankQuery && (
            <button
              onClick={() => setBankQuery("")}
              aria-label="Clear search"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)] hover:text-[var(--foreground)] text-xs font-bold px-1"
            >
              ✕
            </button>
          )}
        </div>

        {loading && (
          <div className="flex items-center justify-center py-6 text-[var(--muted-foreground)] text-xs gap-2">
            <RefreshCw size={14} className="animate-spin" />
            Loading papers…
          </div>
        )}

        {!loading && filteredBank.length === 0 && !failed && (
          <div className="p-6 rounded-xl border border-dashed border-[var(--glass-border-highlight)] text-center text-xs text-[var(--muted-foreground)] space-y-2">
            <p>
              No {level === "All" ? "" : `${level} `}papers
              {bankMedium ? ` (${bankMedium === "sinhala" ? "සිංහල" : "English"} medium)` : ""}
              {bankQuery.trim() ? ` matching “${bankQuery.trim().slice(0, 40)}”` : ""} in
              the bank yet — try another filter.
            </p>
            <p className="opacity-80">
              Your timer, monitoring and notes keep running.
            </p>
          </div>
        )}

        {!loading && failed && (
          <div className="p-4 rounded-xl border border-red-500/25 bg-red-500/[0.06] text-xs text-red-300 flex items-center justify-between gap-2">
            <span>Could not load papers — backend offline or Paper Bank unavailable.</span>
            <button
              onClick={() => void loadData()}
              className="shrink-0 px-2.5 py-1 rounded-lg bg-red-500/15 border border-red-500/30 font-bold hover:brightness-110"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && filteredBank.length > 0 && (
          <>
            <div className="grid gap-2 sm:grid-cols-2 print:grid-cols-1">
              {filteredBank.slice(0, visibleCount).map((p) => {
              const busy = startingId === p.id;
              return (
                <button
                  key={p.id}
                  onClick={() =>
                    void startPaperInline(p.id, p.default_duration_seconds || 3600, p.title)
                  }
                  disabled={startingId !== ""}
                  title={`Start ${p.title} here — same timer, same monitoring`}
                  className="p-3 rounded-xl surface-glass-base hover:border-[var(--ember-line)]/50 transition-all duration-200 text-left group flex items-center justify-between gap-2 print:shadow-none print:border print:border-neutral-300 disabled:opacity-50"
                >
                  <div className="min-w-0">
                    <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">
                      {p.title}
                    </p>
                    <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                      {p.question_count}Q · {p.medium === "sinhala" ? "සිංහල" : "English"} · P{p.paper_no}
                    </p>
                  </div>
                  {busy ? (
                    <Loader2
                      size={14}
                      className="shrink-0 animate-spin text-[var(--primary)]"
                    />
                  ) : (
                    <ChevronRight
                      size={14}
                      className="shrink-0 text-[var(--muted-foreground)] transition-transform duration-200 group-hover:translate-x-1 group-hover:text-[var(--primary)]"
                    />
                  )}
                </button>
              );
            })}
            </div>
            {filteredBank.length > visibleCount && (
              <button
                onClick={() => setVisibleCount((n) => n + PAGE_SIZE)}
                className="w-full py-2 rounded-xl surface-glass-base border border-[var(--glass-border)] text-xs font-bold text-[var(--muted-foreground)] hover:text-[var(--primary)] hover:border-[var(--ember-line)]/50 transition-all"
              >
                Show more ({filteredBank.length - visibleCount} remaining)
              </button>
            )}
            {visibleCount > PAGE_SIZE && filteredBank.length <= visibleCount && filteredBank.length > PAGE_SIZE && (
              <button
                onClick={() => setVisibleCount(PAGE_SIZE)}
                className="w-full py-2 rounded-xl text-xs font-bold text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
              >
                Show less
              </button>
            )}
          </>
        )}

        {startError && (
          <div className="p-4 rounded-xl border border-red-500/25 bg-red-500/[0.06] text-xs text-red-300 flex items-center justify-between gap-2">
            <span>Could not start that paper: {startError}</span>
            <button
              onClick={() => setStartError("")}
              className="shrink-0 px-2.5 py-1 rounded-lg bg-red-500/15 border border-red-500/30 font-bold hover:brightness-110"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>

      {/* Uploaded custom papers — only real user uploads, never Paper-Bank
          sittings or test-harness rows (filtered server-side via
          only_uploads=true plus a client-side honest gate). */}
      {uploadedPapers !== null && !loading && !failed && (
        <div className="space-y-2 pt-2">
          <h4 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
            Your Uploaded Papers
            {uploadedPapers.length > 0 && (
              <span className="ml-1.5 normal-case font-semibold opacity-70">
                ({uploadedPapers.length})
              </span>
            )}
          </h4>
          {uploadedPapers.length === 0 ? (
            <div className="p-5 rounded-xl border border-dashed border-[var(--glass-border-highlight)] text-center text-xs text-[var(--muted-foreground)]">
              No uploaded papers yet — upload a past-paper PDF in the Exam Room
              and it will appear here.
            </div>
          ) : (
            uploadedPapers.map((p) => (
              <div
                key={p.id}
                className="w-full text-left p-3.5 rounded-xl surface-glass-base hover:border-[var(--ember-line)]/50 transition-all duration-200 flex items-center justify-between gap-3 group print:shadow-none print:border print:border-neutral-300"
              >
                <button
                  onClick={() => openPreservingSession(`/exam?exam=${encodeURIComponent(p.id)}`)}
                  title={`Open ${p.title} in Exam Room (new tab, session keeps running)`}
                  className="min-w-0 flex-1 text-left"
                >
                  <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">
                    {p.title}
                  </p>
                  <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                    {p.question_count} questions ·{" "}
                    {p.total_marks > 0 ? `${p.total_marks} marks` : "— marks"} ·{" "}
                    <span className="capitalize">
                      {String(p.status || "ready").replace(/_/g, " ")}
                    </span>
                  </p>
                </button>
                <button
                  onClick={async () => {
                    if (!window.confirm(`Delete "${p.title}"? This cannot be undone.`)) return;
                    try {
                      const res = await apiFetch(apiUrl(`/api/v1/exams/${encodeURIComponent(p.id)}`), {
                        method: "DELETE",
                      });
                      if (!res.ok) throw new Error("Delete failed");
                      setUploadedPapers((prev) => (prev ?? []).filter((x) => x.id !== p.id));
                    } catch {
                      // Honest failure: keep the row so nothing silently vanishes.
                    }
                  }}
                  title={`Delete ${p.title}`}
                  aria-label={`Delete ${p.title}`}
                  className="shrink-0 p-1.5 rounded-lg text-[var(--muted-foreground)] hover:text-red-400 hover:bg-red-500/10 transition-colors text-xs"
                >
                  Delete
                </button>
                <ChevronRight
                  size={15}
                  className="shrink-0 text-[var(--muted-foreground)] transition-transform duration-300 group-hover:translate-x-1 group-hover:text-[var(--primary)]"
                />
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
