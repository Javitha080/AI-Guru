"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  BookOpenCheck,
  Play,
  FileText,
  RefreshCw,
  ChevronRight,
} from "lucide-react";

const cssVars = (o: Record<string, string>) => o as unknown as React.CSSProperties;

export interface PastPaperPanelProps {
  subject: string;
  initialPaperId?: string;
  initialGrade?: number;
}

/**
 * Real past-paper workspace: Paper Bank built-in past papers (English & Sinhala)
 * + uploaded custom exam papers with 1-click start under study telemetry.
 */
export default function PastPaperPanel({
  subject,
  initialPaperId,
  initialGrade,
}: PastPaperPanelProps) {
  const router = useRouter();
  const [bankGrade, setBankGrade] = useState<11 | 13>(
    initialGrade === 11 ? 11 : 13
  );
  const [bankMedium, setBankMedium] = useState<string>("");
  const [bankPapers, setBankPapers] = useState<
    Array<{
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
    }> | null
  >(null);
  const [uploadedPapers, setUploadedPapers] = useState<
    Array<{
      id: string;
      title: string;
      status: string;
      total_marks: number;
      question_count: number;
    }> | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const [bankRes, examRes] = await Promise.all([
        fetch(
          `/api/v1/paper_bank/catalog?subject=${
            bankGrade === 11 ? "ict-ol" : "ict"
          }&grade=${bankGrade}`
        ),
        fetch("/api/v1/exams/list"),
      ]);
      if (bankRes.ok) {
        const bData = await bankRes.json();
        setBankPapers(bData.papers || []);
      }
      if (examRes.ok) {
        const eData = await examRes.json();
        setUploadedPapers(Array.isArray(eData) ? eData : []);
      }
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [bankGrade]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredBank = useMemo(() => {
    if (!bankPapers) return [];
    return bankPapers.filter((p) => !bankMedium || p.medium === bankMedium);
  }, [bankPapers, bankMedium]);

  const selectedPaper = useMemo(() => {
    if (!initialPaperId || !bankPapers) return null;
    return bankPapers.find((p) => p.id === initialPaperId) || null;
  }, [initialPaperId, bankPapers]);

  return (
    <div className="flex-1 p-5 pt-4 overflow-y-auto space-y-4">
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
              router.push(`/papers?sitting=${encodeURIComponent(selectedPaper.id)}`)
            }
            className="shrink-0 px-3.5 py-1.5 rounded-xl bg-[var(--primary)] text-white text-xs font-bold transition-all hover:brightness-110 hover:-translate-y-0.5 active:scale-95 shadow-[0_4px_16px_var(--glow-primary)] flex items-center gap-1.5"
          >
            <Play size={13} fill="currentColor" />
            Open in Paper Bank
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
          </p>
        </div>
        <button
          onClick={() => router.push("/papers")}
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
          </h4>
          <div className="flex items-center gap-1">
            {[
              { grade: 13 as const, label: "A/L" },
              { grade: 11 as const, label: "O/L" },
            ].map(({ grade: g, label }) => (
              <button
                key={g}
                onClick={() => setBankGrade(g)}
                className={`px-3 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                  bankGrade === g
                    ? "bg-[var(--primary)] text-white border-transparent"
                    : "surface-glass-base border-[var(--glass-border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {label}
              </button>
            ))}
            <span className="w-px h-4 bg-[var(--glass-border)] mx-0.5" />
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

        {loading && (
          <div className="flex items-center justify-center py-6 text-[var(--muted-foreground)] text-xs gap-2">
            <RefreshCw size={14} className="animate-spin" />
            Loading papers…
          </div>
        )}

        {!loading && filteredBank.length === 0 && !failed && (
          <div className="p-6 rounded-xl border border-dashed border-[var(--glass-border-highlight)] text-center text-xs text-[var(--muted-foreground)]">
            No built-in papers found for this level / medium filter.
          </div>
        )}

        {!loading && filteredBank.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {filteredBank.slice(0, 8).map((p) => (
              <button
                key={p.id}
                onClick={() => router.push("/papers")}
                className="p-3 rounded-xl surface-glass-base hover:border-[var(--ember-line)]/50 transition-all duration-200 text-left group flex items-center justify-between gap-2"
              >
                <div className="min-w-0">
                  <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">
                    {p.title}
                  </p>
                  <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                    {p.question_count}Q · {p.medium === "sinhala" ? "සිංහල" : "English"} · P{p.paper_no}
                  </p>
                </div>
                <ChevronRight
                  size={14}
                  className="shrink-0 text-[var(--muted-foreground)] transition-transform duration-200 group-hover:translate-x-1 group-hover:text-[var(--primary)]"
                />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Uploaded custom papers */}
      {uploadedPapers && uploadedPapers.length > 0 && (
        <div className="space-y-2 pt-2">
          <h4 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
            Your Uploaded Papers
          </h4>
          {uploadedPapers.map((p) => (
            <button
              key={p.id}
              onClick={() => router.push(`/exam?exam=${encodeURIComponent(p.id)}`)}
              className="w-full text-left p-3.5 rounded-xl surface-glass-base hover:border-[var(--ember-line)]/50 transition-all duration-200 flex items-center justify-between gap-3 group"
            >
              <div className="min-w-0">
                <p className="text-xs font-bold truncate group-hover:text-[var(--primary)] transition-colors">
                  {p.title}
                </p>
                <p className="text-[10px] text-[var(--muted-foreground)] mt-0.5">
                  {p.question_count} questions · {p.total_marks} marks ·{" "}
                  <span className="capitalize">
                    {String(p.status || "ready").replace(/_/g, " ")}
                  </span>
                </p>
              </div>
              <ChevronRight
                size={15}
                className="shrink-0 text-[var(--muted-foreground)] transition-transform duration-300 group-hover:translate-x-1 group-hover:text-[var(--primary)]"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
