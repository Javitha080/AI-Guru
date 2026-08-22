"use client";

/**
 * AI Guru Past-Paper Exam Room.
 *
 * Upload a past-paper PDF -> verbatim question extraction (MCQ first, essays
 * after) -> timed exam runner -> AI grading (deterministic MCQ + LLM essays).
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Upload,
  FileText,
  Clock,
  CheckCircle2,
  XCircle,
  ChevronLeft,
  ChevronRight,
  Send,
  Loader2,
  ListChecks,
  PenLine,
} from "lucide-react";

// ----------------------------------------------------------------- types

interface ExamQuestionView {
  id: string;
  number: number;
  question_type: string;
  text: string;
  options: Record<string, string> | null;
  marks: number;
  section: "mcq" | "essay";
  section_number: number;
}

interface ExamPaperView {
  exam_id: string;
  title: string;
  status: string;
  total_marks: number;
  question_count: number;
  mcq_count: number;
  essay_count: number;
  mcq_duration_seconds: number;
  ends_at: number | null;
  questions: ExamQuestionView[];
  section_boundary: number;
}

interface ResultRow {
  question_id: string;
  number: number;
  question_type: string;
  awarded: number;
  max_marks: number;
  verdict: string;
  feedback: string;
  reference_answer: string | null;
}

type Phase = "upload" | "ready" | "running" | "submitting" | "results";

const api = "/api/v1/exams";

export default function ExamRoomPage() {
  const [phase, setPhase] = useState<Phase>("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [durationMin, setDurationMin] = useState(120);

  const [paper, setPaper] = useState<ExamPaperView | null>(null);
  const [answers, setAnswers] = useState<Record<string, { option_key?: string; answer_text?: string }>>({});
  const [currentIdx, setCurrentIdx] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const [results, setResults] = useState<ResultRow[] | null>(null);
  const [scoreLine, setScoreLine] = useState<{ total_score: number; total_marks: number } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const submittingRef = useRef(false);

  // ----------------------------------------------------------- countdown
  useEffect(() => {
    if (phase !== "running") return;
    const t = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          clearInterval(t);
          void doSubmit();
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const orderedQuestions = useMemo(() => paper?.questions ?? [], [paper]);
  const current = orderedQuestions[currentIdx];

  // ------------------------------------------------------------- actions
  const handlePreview = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${api}/parse-preview`, { method: "POST", body: fd });
      if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || "Extraction failed");
      await res.json();
      setPhase("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to analyze PDF");
    } finally {
      setBusy(false);
    }
  }, [file]);

  const handleUploadAndStart = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (title.trim()) fd.append("title", title.trim());
      fd.append("duration_seconds", String(durationMin * 60));
      const res = await fetch(`${api}/upload`, { method: "POST", body: fd });
      if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || "Upload failed");
      const meta = await res.json();
      const startRes = await fetch(`${api}/${meta.exam_id}/start`, { method: "POST" });
      if (!startRes.ok) throw new Error("Could not start the exam timer");
      const started = await startRes.json();

      const paperRes = await fetch(`${api}/${meta.exam_id}`);
      if (!paperRes.ok) throw new Error("Could not load the exam paper");
      const paperData: ExamPaperView = await paperRes.json();
      setPaper(paperData);
      setSecondsLeft(Math.max(60, Math.round((started.ends_at - Date.now() / 1000))));
      setPhase("running");
      setCurrentIdx(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to prepare exam");
    } finally {
      setBusy(false);
    }
  }, [file, title, durationMin]);

  const doSubmit = useCallback(async () => {
    if (!paper) return;
    if (submittingRef.current) return;
    submittingRef.current = true;
    setPhase("submitting");
    try {
      const payload = {
        student_id: "student-primary",
        answers: Object.entries(answers).map(([question_id, a]) => ({
          question_id,
          option_key: a.option_key ?? "",
          answer_text: a.answer_text ?? "",
        })),
      };
      const res = await fetch(`${api}/${paper.exam_id}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || "Submission failed");
      const data = await res.json();
      setResults(data.results as ResultRow[]);
      setScoreLine({ total_score: data.total_score, total_marks: data.total_marks });
      setPhase("results");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submission failed");
      setPhase("running");
    } finally {
      submittingRef.current = false;
    }
  }, [paper, answers]);

  const setAnswer = (qid: string, patch: { option_key?: string; answer_text?: string }) =>
    setAnswers((prev) => ({ ...prev, [qid]: { ...prev[qid], ...patch } }));

  const answeredCount = Object.values(answers).filter(
    (a) => (a.option_key ?? "").trim() || (a.answer_text ?? "").trim()
  ).length;

  const fmtTime = (s: number) =>
    `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  // ------------------------------------------------------------- render
  return (
    <div className="flex-1 h-full overflow-y-auto bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-indigo-100 dark:bg-indigo-900/50 flex items-center justify-center text-indigo-600 dark:text-indigo-400">
            <FileText size={22} />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight">Past-Paper Exam Room</h1>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Your past papers, exactly as printed — timed, answered, and AI-graded.
            </p>
          </div>
        </div>

        {error && (
          <div className="p-3 rounded-xl bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
            {error}
          </div>
        )}

        {/* PHASE: UPLOAD */}
        {(phase === "upload" || phase === "ready") && (
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6 space-y-5">
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const f = e.dataTransfer.files?.[0];
                if (f && f.name.toLowerCase().endsWith(".pdf")) setFile(f);
              }}
              className="cursor-pointer rounded-2xl border-2 border-dashed border-gray-300 dark:border-gray-600 hover:border-indigo-400 p-10 text-center transition-colors"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <Upload size={28} className="mx-auto mb-3 text-gray-400" />
              <p className="text-sm font-semibold">{file ? file.name : "Click or drop your past-paper PDF"}</p>
              <p className="text-xs text-gray-400 mt-1">Questions are extracted verbatim — nothing is rewritten.</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block">
                <span className="text-xs font-bold text-gray-500">Exam Title (optional)</span>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Mathematics 2023 Paper II"
                  className="mt-1 w-full px-3 py-2 rounded-xl bg-transparent border border-gray-300 dark:border-gray-600 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="text-xs font-bold text-gray-500">Duration (minutes)</span>
                <input
                  type="number"
                  min={5}
                  max={360}
                  value={durationMin}
                  onChange={(e) => setDurationMin(Number(e.target.value))}
                  className="mt-1 w-full px-3 py-2 rounded-xl bg-transparent border border-gray-300 dark:border-gray-600 text-sm focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                />
              </label>
            </div>

            <button
              disabled={!file || busy}
              onClick={handleUploadAndStart}
              className="w-full py-3 rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white font-bold flex items-center justify-center gap-2 transition-colors"
            >
              {busy ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              {busy ? "Extracting questions…" : `Create & Start ${durationMin}-min Exam`}
            </button>
          </div>
        )}

        {/* PHASE: RUNNING */}
        {(phase === "running" || phase === "submitting") && paper && (
          <div className="space-y-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 px-5 py-3 flex items-center justify-between sticky top-2 z-10 shadow-sm">
              <div>
                <p className="font-bold text-sm">{paper.title}</p>
                <p className="text-[11px] text-gray-500">
                  Answered {answeredCount}/{orderedQuestions.length}
                </p>
              </div>
              <div
                className={`font-mono font-bold text-lg px-3 py-1 rounded-xl ${
                  secondsLeft < 300 ? "text-red-500" : "text-indigo-600 dark:text-indigo-400"
                }`}
              >
                <Clock size={16} className="inline mr-1 -mt-1" />
                {fmtTime(secondsLeft)}
              </div>
            </div>

            {current && (
              <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6 space-y-5">
                <div className="flex items-center gap-2">
                  {current.section === "mcq" ? (
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 flex items-center gap-1">
                      <ListChecks size={11} /> SECTION A · MCQ
                    </span>
                  ) : (
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300 flex items-center gap-1">
                      <PenLine size={11} /> SECTION B · WRITTEN
                    </span>
                  )}
                  <span className="text-[10px] text-gray-400">
                    Question {current.section_number} of {orderedQuestions.length} · {current.marks} mark{current.marks !== 1 ? "s" : ""}
                  </span>
                </div>

                <p className="text-base leading-relaxed whitespace-pre-wrap font-medium">{current.text}</p>

                {current.options ? (
                  <div className="grid gap-2">
                    {Object.entries(current.options)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([key, value]) => {
                        const selected = answers[current.id]?.option_key === key;
                        return (
                          <button
                            key={key}
                            onClick={() => setAnswer(current.id, { option_key: key })}
                            className={`text-left px-4 py-2.5 rounded-xl border text-sm transition-all ${
                              selected
                                ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 font-semibold"
                                : "border-gray-200 dark:border-gray-600 hover:border-indigo-300"
                            }`}
                          >
                            <span className="font-mono font-bold mr-2">{key}.</span>
                            {value}
                          </button>
                        );
                      })}
                  </div>
                ) : (
                  <textarea
                    rows={7}
                    value={answers[current.id]?.answer_text ?? ""}
                    onChange={(e) => setAnswer(current.id, { answer_text: e.target.value })}
                    placeholder="Write your full answer here — AI Guru will grade it against the marking scheme…"
                    className="w-full p-4 text-sm font-mono bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                  />
                )}

                <div className="flex items-center justify-between pt-2">
                  <button
                    disabled={currentIdx === 0}
                    onClick={() => setCurrentIdx((i) => Math.max(0, i - 1))}
                    className="px-4 py-2 rounded-xl text-sm font-semibold border border-gray-300 dark:border-gray-600 disabled:opacity-40 flex items-center gap-1"
                  >
                    <ChevronLeft size={15} /> Prev
                  </button>

                  <div className="flex gap-1.5 flex-wrap justify-center max-w-[55%] overflow-y-auto">
                    {orderedQuestions.map((q, i) => (
                      <button
                        key={q.id}
                        onClick={() => setCurrentIdx(i)}
                        className={`h-7 w-7 rounded-lg text-[10px] font-bold ${
                          i === currentIdx
                            ? "bg-indigo-600 text-white"
                            : answers[q.id]?.option_key || answers[q.id]?.answer_text
                              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                              : "bg-gray-100 text-gray-500 dark:bg-gray-700"
                        }`}
                      >
                        {i + 1}
                      </button>
                    ))}
                  </div>

                  {currentIdx < orderedQuestions.length - 1 ? (
                    <button
                      onClick={() => setCurrentIdx((i) => i + 1)}
                      className="px-4 py-2 rounded-xl text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 flex items-center gap-1"
                    >
                      Next <ChevronRight size={15} />
                    </button>
                  ) : (
                    <button
                      onClick={() => void doSubmit()}
                      disabled={phase === "submitting"}
                      className="px-5 py-2 rounded-xl text-sm font-bold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-1.5"
                    >
                      {phase === "submitting" ? <Loader2 size={15} className="animate-spin" /> : <Send size={14} />}
                      Submit Paper
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* PHASE: RESULTS */}
        {phase === "results" && results && (
          <div className="space-y-4">
            <div className="bg-gradient-to-r from-indigo-600 to-purple-600 rounded-2xl p-6 text-white flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-wide opacity-80">Total Score</p>
                <p className="text-4xl font-extrabold font-mono">
                  {scoreLine?.total_score ?? 0}
                  <span className="text-lg opacity-75"> / {scoreLine?.total_marks ?? 0}</span>
                </p>
              </div>
              <CheckCircle2 size={48} className="opacity-60" />
            </div>

            {results.map((r) => (
              <div key={r.question_id} className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-5 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-500">Question {r.number}</span>
                  <span className="flex items-center gap-2 text-xs font-bold">
                    {r.verdict === "correct" ? (
                      <span className="text-green-600 flex items-center gap-1"><CheckCircle2 size={14} /> Correct</span>
                    ) : r.verdict === "partial" ? (
                      <span className="text-amber-600">Partial</span>
                    ) : r.verdict === "incorrect" ? (
                      <span className="text-red-600 flex items-center gap-1"><XCircle size={14} /> Incorrect</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                    <span className="font-mono">
                      {r.awarded}/{r.max_marks}
                    </span>
                  </span>
                </div>
                {r.feedback && <p className="text-sm text-gray-600 dark:text-gray-300">{r.feedback}</p>}
                {r.reference_answer && (
                  <details className="text-xs text-gray-500">
                    <summary className="cursor-pointer font-semibold">Reference answer</summary>
                    <p className="mt-1 whitespace-pre-wrap">{r.reference_answer}</p>
                  </details>
                )}
              </div>
            ))}

            <button
              onClick={() => {
                setPhase("upload");
                setFile(null);
                setPaper(null);
                setResults(null);
                setAnswers({});
                setTitle("");
              }}
              className="w-full py-3 rounded-xl border border-gray-300 dark:border-gray-600 font-bold text-sm hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              Take Another Paper
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
