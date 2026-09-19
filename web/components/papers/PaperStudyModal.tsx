"use client";

/**
 * AI Guru Paper Study & Preview Modal.
 * LiquidGlass & Bento Grid aesthetic for non-timed past-paper study:
 * - High-fidelity KaTeX LaTeX math formulas and Markdown rendering
 * - Verbatim diagram inspection (circuits, flowcharts, ER diagrams) with lightbox zoom
 * - Question navigator pills with quick jump
 * - Interactive marking scheme and official explanation reveals
 * - Seamless transition to timed exam mode
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Eye,
  EyeOff,
  FileText,
  HelpCircle,
  Image as ImageIcon,
  Loader2,
  Play,
  Sparkles,
  X,
  ZoomIn,
} from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { BankPaperDetail, BankQuestion, papersApi } from "@/lib/papers/paper-api";

const NUM_TO_LETTER: Record<string, string> = {
  "1": "A", "2": "B", "3": "C", "4": "D", "5": "E",
};

const LETTER_TO_NUM: Record<string, string> = {
  A: "1", B: "2", C: "3", D: "4", E: "5",
};

interface PaperStudyModalProps {
  bankPaperId: string;
  onClose: () => void;
  onStartExam?: (paperId: string) => void;
}

export default function PaperStudyModal({
  bankPaperId,
  onClose,
  onStartExam,
}: PaperStudyModalProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<BankPaperDetail | null>(null);
  const [revealedQuestions, setRevealedQuestions] = useState<Record<string, boolean>>({});
  const [revealAll, setRevealAll] = useState(false);
  const [zoomImage, setZoomImage] = useState<{ src: string; alt: string; caption?: string } | null>(null);
  const [activeQId, setActiveQId] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    // Fetch paper with includeAnswers = true for study mode
    papersApi
      .getPaper(bankPaperId, true)
      .then((res) => {
        if (!cancelled) {
          setDetail(res);
          if (res.paper.questions.length > 0) {
            setActiveQId(res.paper.questions[0].id);
          }
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [bankPaperId]);

  const questions = useMemo(() => detail?.paper?.questions ?? [], [detail]);

  const toggleReveal = (qId: string) => {
    setRevealedQuestions((prev) => ({
      ...prev,
      [qId]: !prev[qId],
    }));
  };

  const handleToggleRevealAll = () => {
    const nextState = !revealAll;
    setRevealAll(nextState);
    const newRevealed: Record<string, boolean> = {};
    for (const q of questions) {
      newRevealed[q.id] = nextState;
    }
    setRevealedQuestions(newRevealed);
  };

  const scrollToQuestion = (qId: string) => {
    setActiveQId(qId);
    const el = document.getElementById(`q-card-${qId}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const askAiGuru = (q: BankQuestion) => {
    const ctx = `Question ${q.number}: ${q.stem || q.text}\nOptions:\n${JSON.stringify(q.options, null, 2)}\nReference Answer: ${q.reference_answer || "N/A"}`;
    window.dispatchEvent(
      new CustomEvent("aiguru:open-floating-chat", {
        detail: {
          context: ctx,
          initialPrompt: `Help me understand Question ${q.number} from this past paper: "${q.stem || q.text}". What is the core concept and step-by-step reasoning?`,
        },
      })
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/75 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative flex flex-col w-full max-w-5xl h-[92vh] surface-glass-elevated border border-[var(--glass-border)] rounded-3xl shadow-2xl overflow-hidden text-[var(--foreground)]">
        {/* Modal Top Header */}
        <header className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)] surface-glass-base shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={onClose}
              className="p-2 rounded-xl surface-glass-base hover:bg-white/10 transition-colors text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              aria-label="Back to catalog"
              title="Back"
            >
              <ArrowLeft size={16} />
            </button>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wider bg-[var(--ember-0)] text-[var(--primary)] border border-[var(--ember-line)]/30">
                  <BookOpen size={11} /> Study &amp; Review Mode
                </span>
                {detail && (
                  <>
                    <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-[var(--muted)] text-[var(--foreground)] border border-[var(--glass-border)]">
                      {detail.grade === 11 ? "O/L" : "A/L"}
                    </span>
                    <span className="text-xs font-semibold text-[var(--muted-foreground)] capitalize">
                      {detail.medium} Medium
                    </span>
                  </>
                )}
              </div>
              <h2 className="text-base sm:text-lg font-bold truncate mt-0.5">
                {detail ? detail.paper.title : "Loading Paper…"}
              </h2>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {questions.length > 0 && (
              <button
                onClick={handleToggleRevealAll}
                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl surface-glass-base border border-[var(--glass-border)] text-xs font-semibold hover:border-[var(--ember-line)] transition-all"
                title={revealAll ? "Hide all answers" : "Reveal all answers"}
              >
                {revealAll ? <EyeOff size={13} /> : <Eye size={13} />}
                <span>{revealAll ? "Hide All Keys" : "Reveal All Keys"}</span>
              </button>
            )}

            {onStartExam && detail && (
              <button
                onClick={() => {
                  onClose();
                  onStartExam(detail.bank_paper_id);
                }}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-[var(--primary)] text-white text-xs font-bold shadow-[0_2px_12px_var(--glow-primary)] hover:opacity-95 transition-all"
              >
                <Play size={13} className="fill-current" />
                <span>Timed Exam</span>
              </button>
            )}

            <button
              onClick={onClose}
              className="p-2 rounded-xl surface-glass-base hover:bg-white/10 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
              aria-label="Close study viewer"
            >
              <X size={18} />
            </button>
          </div>
        </header>

        {/* Loading / Error States */}
        {loading && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center p-8">
            <Loader2 size={32} className="animate-spin text-[var(--primary)]" />
            <p className="text-sm font-semibold">Loading past paper questions &amp; diagrams…</p>
            <p className="text-xs text-[var(--muted-foreground)]">Preparing KaTeX math formulas and marking guides</p>
          </div>
        )}

        {error && (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-3">
            <div className="p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm max-w-md">
              <p className="font-bold">Failed to load paper</p>
              <p className="text-xs mt-1">{error}</p>
            </div>
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl surface-glass-base text-xs font-bold hover:text-[var(--primary)]"
            >
              Close
            </button>
          </div>
        )}

        {/* Main Content Body */}
        {!loading && !error && detail && (
          <div className="flex-1 min-h-0 flex flex-col md:flex-row overflow-hidden">
            {/* Left / Top Quick Navigation Rail */}
            <aside className="w-full md:w-56 shrink-0 border-b md:border-b-0 md:border-r border-[var(--glass-border)] surface-glass-base/50 p-3 overflow-x-auto md:overflow-y-auto flex md:flex-col gap-1.5 [scrollbar-gutter:stable]">
              <div className="hidden md:flex items-center justify-between px-2 py-1 text-[11px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">
                <span>Questions ({questions.length})</span>
                <span className="text-[10px] lowercase">{detail.paper_type}</span>
              </div>
              <div className="flex md:grid md:grid-cols-4 gap-1.5">
                {questions.map((q) => {
                  const isRevealed = revealAll || revealedQuestions[q.id];
                  const hasDiagrams = q.diagrams && q.diagrams.length > 0;
                  const isActive = activeQId === q.id;

                  return (
                    <button
                      key={q.id}
                      onClick={() => scrollToQuestion(q.id)}
                      className={`relative px-2.5 py-1.5 md:py-2 rounded-xl text-xs font-bold transition-all flex items-center justify-center gap-1 ${
                        isActive
                          ? "bg-[var(--primary)] text-white shadow-md scale-[1.03]"
                          : isRevealed
                            ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                            : "surface-glass-base border border-[var(--glass-border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--ember-line)]"
                      }`}
                      title={`Jump to Question ${q.number}`}
                    >
                      <span>Q{q.number}</span>
                      {hasDiagrams && (
                        <ImageIcon size={10} className={isActive ? "text-white/80" : "text-[var(--primary)]"} />
                      )}
                    </button>
                  );
                })}
              </div>
            </aside>

            {/* Questions Scroll View */}
            <main className="flex-1 min-h-0 overflow-y-auto p-4 sm:p-6 space-y-6 [scrollbar-gutter:stable]">
              {questions.map((q) => {
                const isRevealed = revealAll || revealedQuestions[q.id];
                const isMcq = q.question_type === "choice" || Boolean(q.options && Object.keys(q.options).length > 0);
                const isSinhalaMedium = detail.medium === "sinhala";
                const refAns = q.reference_answer?.trim() || "";

                return (
                  <article
                    key={q.id}
                    id={`q-card-${q.id}`}
                    className="p-5 sm:p-6 rounded-2xl border border-[var(--glass-border)] surface-glass-base shadow-sm space-y-4 transition-all hover:border-[var(--glass-border-highlight)]"
                  >
                    {/* Question Header */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <span className="w-8 h-8 rounded-xl bg-[var(--ember-0)] border border-[var(--ember-line)]/40 text-[var(--primary)] flex items-center justify-center font-bold text-xs">
                          {q.number}
                        </span>
                        <span className="text-xs font-bold uppercase tracking-wide text-[var(--muted-foreground)]">
                          Question {q.number}
                        </span>
                        {q.marks > 0 && (
                          <span className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-[var(--muted)] text-[var(--muted-foreground)]">
                            {q.marks} {q.marks === 1 ? "mark" : "marks"}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => askAiGuru(q)}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg surface-glass-base border border-[var(--glass-border)] text-xs font-semibold text-[var(--primary)] hover:border-[var(--ember-line)] transition-all"
                          title="Ask AI Guru about this question"
                        >
                          <Sparkles size={12} />
                          <span className="hidden sm:inline">Ask AI Tutor</span>
                        </button>
                        <button
                          onClick={() => toggleReveal(q.id)}
                          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                            isRevealed
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                              : "surface-glass-base border border-[var(--glass-border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                          }`}
                        >
                          {isRevealed ? <EyeOff size={12} /> : <Eye size={12} />}
                          <span>{isRevealed ? "Hide Key" : "View Key"}</span>
                        </button>
                      </div>
                    </div>

                    {/* Question Stem (Math + Markdown) */}
                    <div className="text-sm leading-relaxed font-normal whitespace-pre-wrap break-words">
                      <MarkdownRenderer content={q.stem || q.text || ""} enableMath />
                    </div>

                    {/* Diagrams / Circuit schematics / Flowcharts */}
                    {q.diagrams && q.diagrams.length > 0 && (
                      <div className="flex flex-col sm:flex-row flex-wrap gap-4 my-3">
                        {q.diagrams.map((diag, dIdx) => {
                          const cleanSrc = (diag.src || "").replace(/^\/?images\//, "");
                          const assetUrl = `/api/v1/paper_bank/assets/${detail.bank_paper_id}/${cleanSrc}`;
                          return (
                            <figure
                              key={diag.id || dIdx}
                              className="group relative rounded-2xl border border-[var(--glass-border)] p-3 surface-glass-base shadow-sm max-w-full overflow-hidden flex flex-col items-center cursor-zoom-in"
                              onClick={() =>
                                setZoomImage({
                                  src: assetUrl,
                                  alt: diag.alt || `Diagram for Question ${q.number}`,
                                  caption: diag.caption,
                                })
                              }
                            >
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={assetUrl}
                                alt={diag.alt || diag.caption || `Diagram for Question ${q.number}`}
                                className="max-h-72 max-w-full object-contain rounded-xl bg-white p-2 transition-transform group-hover:scale-[1.01]"
                                loading="lazy"
                              />
                              <div className="absolute top-2 right-2 p-1.5 rounded-lg bg-black/60 text-white/80 opacity-0 group-hover:opacity-100 transition-opacity">
                                <ZoomIn size={14} />
                              </div>
                              {diag.caption && (
                                <figcaption className="text-xs text-center text-[var(--muted-foreground)] mt-2 font-medium">
                                  {diag.caption}
                                </figcaption>
                              )}
                            </figure>
                          );
                        })}
                      </div>
                    )}

                    {/* Options (MCQ) */}
                    {isMcq && q.options && (
                      <div className="space-y-2 mt-3">
                        {Object.entries(q.options).map(([key, val]) => {
                          const numKey = LETTER_TO_NUM[key.toUpperCase()] ?? key;
                          const letterKey = NUM_TO_LETTER[key] ?? key;
                          const isCorrectOption =
                            isRevealed &&
                            refAns &&
                            (refAns.toUpperCase() === key.toUpperCase() ||
                              refAns.toUpperCase() === letterKey.toUpperCase() ||
                              refAns === numKey);

                          return (
                            <div
                              key={key}
                              className={`p-3.5 rounded-xl border flex items-start gap-3 transition-all ${
                                isCorrectOption
                                  ? "border-emerald-500/70 bg-emerald-500/10 shadow-[0_0_15px_rgba(16,185,129,0.15)]"
                                  : "border-[var(--glass-border)] surface-glass-base/70"
                              }`}
                            >
                              <span
                                className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 ${
                                  isCorrectOption
                                    ? "bg-emerald-500 text-white shadow-sm"
                                    : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                                }`}
                              >
                                {isSinhalaMedium && NUM_TO_LETTER[key]
                                  ? `(${key})`
                                  : isSinhalaMedium && LETTER_TO_NUM[key]
                                    ? `(${LETTER_TO_NUM[key]})`
                                    : key}
                              </span>
                              <div className="text-sm leading-snug pt-0.5 flex-1 whitespace-pre-wrap break-words">
                                <MarkdownRenderer content={val} enableMath className="inline-block" />
                              </div>
                              {isCorrectOption && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-500/20 text-emerald-300 shrink-0">
                                  <CheckCircle2 size={11} /> Correct
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Structured Sub-questions (Paper 2) */}
                    {q.sub_questions && q.sub_questions.length > 0 && (
                      <div className="space-y-3 mt-4 pl-3 border-l-2 border-[var(--primary)]/30">
                        {q.sub_questions.map((sq, sIdx) => (
                          <div key={sq.sub_id || sIdx} className="space-y-1.5 text-xs">
                            <div className="flex items-baseline gap-2 font-semibold">
                              <span className="text-[var(--primary)]">Part ({sq.label}):</span>
                              <span className="text-[var(--muted-foreground)] font-normal">
                                ({sq.marks} marks)
                              </span>
                            </div>
                            <div className="text-sm text-[var(--foreground)]">
                              <MarkdownRenderer content={sq.stem} enableMath />
                            </div>
                            {isRevealed && (sq.expected_answer || sq.marking_guide) && (
                              <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs space-y-1 text-emerald-200">
                                {sq.expected_answer && (
                                  <p>
                                    <span className="font-bold">Key: </span>
                                    {sq.expected_answer}
                                  </p>
                                )}
                                {sq.marking_guide && (
                                  <p className="italic text-emerald-300/80">
                                    <span className="font-bold not-italic">Scheme: </span>
                                    {sq.marking_guide}
                                  </p>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Solution / Marking Scheme Card */}
                    {isRevealed && (
                      <div className="p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 space-y-2.5 animate-in fade-in duration-150">
                        <div className="flex items-center justify-between text-xs font-bold text-emerald-400">
                          <span className="flex items-center gap-1.5">
                            <CheckCircle2 size={14} /> Official Marking Scheme &amp; Answer
                          </span>
                          {refAns && (
                            <span className="px-2.5 py-0.5 rounded-md bg-emerald-500 text-white font-mono font-extrabold text-xs">
                              Answer: {refAns}
                            </span>
                          )}
                        </div>

                        {q.explanation && (
                          <div className="text-xs leading-relaxed text-[var(--muted-foreground)] p-3 rounded-lg surface-glass-base border border-[var(--glass-border)]">
                            <p className="font-semibold text-[var(--foreground)] mb-1">
                              Step-by-step Syllabus Explanation:
                            </p>
                            <MarkdownRenderer content={q.explanation} enableMath />
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                );
              })}
            </main>
          </div>
        )}
      </div>

      {/* Lightbox / Zoom Dialog */}
      {zoomImage && (
        <div
          className="fixed inset-0 z-60 bg-black/90 flex flex-col items-center justify-center p-4 cursor-zoom-out animate-in fade-in duration-150"
          onClick={() => setZoomImage(null)}
        >
          <div className="relative max-w-4xl max-h-[85vh] flex flex-col items-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={zoomImage.src}
              alt={zoomImage.alt}
              className="max-h-[75vh] max-w-full object-contain rounded-2xl bg-white p-4 shadow-2xl"
            />
            {zoomImage.caption && (
              <p className="text-sm font-semibold text-white/90 mt-3 text-center">
                {zoomImage.caption}
              </p>
            )}
            <button
              onClick={() => setZoomImage(null)}
              className="absolute -top-10 right-0 p-2 rounded-full bg-white/20 hover:bg-white/30 text-white transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
