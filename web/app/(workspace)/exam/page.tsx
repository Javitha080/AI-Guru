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
  Code,
  ImagePlus,
  Trash2,
  Paperclip,
} from "lucide-react";

// ----------------------------------------------------------------- types

interface AnswerImage {
  id: string;
  base64?: string | null;
  url?: string | null;
  filename: string;
  mime: string;
  previewUrl?: string | null;
}

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

const NUM_TO_LETTER: Record<string, string> = { "1": "A", "2": "B", "3": "C", "4": "D", "5": "E" };
const LETTER_TO_NUM: Record<string, string> = { A: "1", B: "2", C: "3", D: "4", E: "5" };

function extractSubParts(text: string): Array<{ label: string; title: string }> {
  const lines = text.split("\n");
  const parts: Array<{ label: string; title: string }> = [];
  const rx = /^\s*(\([a-zA-Z0-9ivxIVX\u0d80-\u0dff]+\))\s+(.*)$/;
  let curLabel = "";
  let curBuf: string[] = [];
  for (const line of lines) {
    const m = line.match(rx);
    if (m) {
      if (curLabel) parts.push({ label: curLabel, title: curBuf.join(" ").trim() });
      curLabel = m[1];
      curBuf = [m[2]];
    } else if (curLabel) {
      curBuf.push(line);
    }
  }
  if (curLabel) parts.push({ label: curLabel, title: curBuf.join(" ").trim() });
  return parts;
}

export default function ExamRoomPage() {
  const [phase, setPhase] = useState<Phase>("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [durationMin, setDurationMin] = useState(120);

  const [paper, setPaper] = useState<ExamPaperView | null>(null);
  const [answers, setAnswers] = useState<
    Record<string, { option_key?: string; answer_text?: string; images?: AnswerImage[]; sub_answers?: Record<string, string> }>
  >({});
  const [currentIdx, setCurrentIdx] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [codeMode, setCodeMode] = useState(false);
  const [activeSubPart, setActiveSubPart] = useState<string | null>(null);

  const [results, setResults] = useState<ResultRow[] | null>(null);
  const [scoreLine, setScoreLine] = useState<{ total_score: number; total_marks: number } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
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

  // Deep link: /exam?exam=<id> opens an existing paper (from Study Room's
  // "Your Papers" list) — resumes a running timer or shows graded results.
  const deepLinkDoneRef = useRef(false);
  useEffect(() => {
    if (deepLinkDoneRef.current) return;
    deepLinkDoneRef.current = true;
    const id = new URLSearchParams(window.location.search).get("exam");
    if (!id) return;
    (async () => {
      setBusy(true);
      setError("");
      try {
        const res = await fetch(`${api}/${encodeURIComponent(id)}`);
        if (!res.ok) throw new Error("Exam not found");
        const meta = await res.json();
        const status = String(meta.status || "created");

        if (status === "graded" || status === "submitted") {
          const r = await fetch(`${api}/${encodeURIComponent(id)}/result`);
          if (!r.ok) throw new Error("Could not load the saved result");
          const data = await r.json();
          setResults(data.results as ResultRow[]);
          setScoreLine({ total_score: data.total_score, total_marks: data.total_marks });
          setPhase("results");
          return;
        }

        let endsAt: number | null = typeof meta.ends_at === "number" ? meta.ends_at : null;
        if (status !== "active") {
          const startRes = await fetch(`${api}/${encodeURIComponent(id)}/start`, { method: "POST" });
          if (!startRes.ok) throw new Error("Could not start the exam timer");
          const started = await startRes.json();
          endsAt = started.ends_at;
        }

        setPaper(meta);
        setCurrentIdx(0);
        const remaining = endsAt ? Math.round(endsAt - Date.now() / 1000) : 60;
        // An already-elapsed timer grades whatever was answered — same
        // semantics as the in-exam countdown hitting zero.
        setSecondsLeft(Math.max(0, remaining));
        setPhase("running");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to open the linked exam");
      } finally {
        setBusy(false);
      }
    })();
  }, []);

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

  const setAnswer = (qid: string, patch: { option_key?: string; answer_text?: string; images?: AnswerImage[]; sub_answers?: Record<string, string> }) =>
    setAnswers((prev) => ({ ...prev, [qid]: { ...prev[qid], ...patch } }));

  const subParts = useMemo(() => {
    if (!current || current.section === "mcq") return [];
    return extractSubParts(current.text);
  }, [current]);

  useEffect(() => {
    if (subParts.length > 0) {
      setActiveSubPart(subParts[0].label);
    } else {
      setActiveSubPart(null);
    }
  }, [subParts]);

  const handleSubPartChange = (qid: string, partLabel: string, text: string) => {
    const existing = answers[qid]?.sub_answers ?? {};
    const updated = { ...existing, [partLabel]: text };
    const combined = subParts
      .map((item) => {
        const ans = (updated[item.label] ?? "").trim();
        return ans ? `${item.label} ${ans}` : "";
      })
      .filter(Boolean)
      .join("\n\n");
    setAnswer(qid, { sub_answers: updated, answer_text: combined || text });
  };

  const handleImageUpload = (qid: string, e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const currentImages = answers[qid]?.images ?? [];
    Array.from(files).forEach((file) => {
      if (!file.type.startsWith("image/")) return;
      const reader = new FileReader();
      reader.onload = (loadEvt) => {
        const base64Data = loadEvt.target?.result as string;
        const newImg: AnswerImage = {
          id: Math.random().toString(36).slice(2, 11),
          base64: base64Data.split(",")[1] ?? base64Data,
          previewUrl: URL.createObjectURL(file),
          filename: file.name,
          mime: file.type,
        };
        setAnswer(qid, { images: [...currentImages, newImg] });
      };
      reader.readAsDataURL(file);
    });
    if (e.target) e.target.value = "";
  };

  const handleRemoveImage = (qid: string, imgId: string) => {
    const currentImages = answers[qid]?.images ?? [];
    setAnswer(qid, { images: currentImages.filter((img) => img.id !== imgId) });
  };

  const answeredCount = Object.values(answers).filter(
    (a) => (a.option_key ?? "").trim() || (a.answer_text ?? "").trim() || ((a.images?.length ?? 0) > 0)
  ).length;
  const currentImages = answers[current?.id]?.images ?? [];

  const fmtTime = (s: number) =>
    `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  // ------------------------------------------------------------- render
  return (
    <div className="flex-1 h-full overflow-y-auto bg-gray-50 dark:bg-[var(--secondary)] text-[var(--foreground)]">
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-[var(--accent)] flex items-center justify-center text-[var(--primary)]">
            <FileText size={22} />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight">Past-Paper Exam Room</h1>
            <p className="text-xs text-[var(--muted-foreground)]">
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
          <div className="bg-[var(--card)] rounded-2xl border border-[var(--border)] p-6 space-y-5">
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const f = e.dataTransfer.files?.[0];
                if (f && f.name.toLowerCase().endsWith(".pdf")) setFile(f);
              }}
              className="cursor-pointer rounded-2xl border-2 border-dashed border-[var(--border)] hover:border-[var(--primary)] p-10 text-center transition-colors"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <Upload size={28} className="mx-auto mb-3 text-[var(--muted-foreground)]" />
              <p className="text-sm font-semibold">{file ? file.name : "Click or drop your past-paper PDF"}</p>
              <p className="text-xs text-[var(--muted-foreground)] mt-1">Questions are extracted verbatim — nothing is rewritten.</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block">
                <span className="text-xs font-bold text-gray-500">Exam Title (optional)</span>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Mathematics 2023 Paper II"
                  className="mt-1 w-full px-3 py-2 rounded-xl bg-transparent border border-[var(--border)] text-sm focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
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
                  className="mt-1 w-full px-3 py-2 rounded-xl bg-transparent border border-[var(--border)] text-sm focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
                />
              </label>
            </div>

            <button
              disabled={!file || busy}
              onClick={handleUploadAndStart}
              className="w-full py-3 rounded-xl bg-[var(--primary)] hover:brightness-110 disabled:opacity-40 text-white font-bold flex items-center justify-center gap-2 transition-colors"
            >
              {busy ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              {busy ? "Extracting questions…" : `Create & Start ${durationMin}-min Exam`}
            </button>
          </div>
        )}

        {/* PHASE: RUNNING */}
        {(phase === "running" || phase === "submitting") && paper && (
          <div className="space-y-4">
            <div className="bg-[var(--card)] rounded-2xl border border-[var(--border)] px-5 py-3 flex items-center justify-between sticky top-2 z-10 shadow-sm">
              <div>
                <p className="font-bold text-sm">{paper.title}</p>
                <p className="text-[11px] text-gray-500">
                  Answered {answeredCount}/{orderedQuestions.length}
                </p>
              </div>
              <div
                className={`font-mono font-bold text-lg px-3 py-1 rounded-xl ${
                  secondsLeft < 300 ? "text-red-500" : "text-[var(--primary)]"
                }`}
              >
                <Clock size={16} className="inline mr-1 -mt-1" />
                {fmtTime(secondsLeft)}
              </div>
            </div>

            {current && (
              <div className="bg-[var(--card)] rounded-2xl border border-[var(--border)] p-6 space-y-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    {current.section === "mcq" ? (
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 flex items-center gap-1">
                        <ListChecks size={11} /> SECTION A · MCQ
                      </span>
                    ) : (
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-[var(--accent)] text-[var(--primary)] flex items-center gap-1">
                        <PenLine size={11} /> SECTION B · WRITTEN
                      </span>
                    )}
                    <span className="text-[10px] text-[var(--muted-foreground)]">
                      Question {current.section_number} of {orderedQuestions.length} · {current.marks} mark{current.marks !== 1 ? "s" : ""}
                    </span>
                  </div>
                  {current.section !== "mcq" && (
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => setCodeMode(!codeMode)}
                        className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition-colors flex items-center gap-1 ${
                          codeMode
                            ? "bg-[var(--primary)] text-white border-transparent"
                            : "surface-glass-base border-[var(--border)] text-[var(--muted-foreground)]"
                        }`}
                        title="Toggle code / monospaced font mode"
                      >
                        <Code size={12} /> Code mode
                      </button>
                      <button
                        onClick={() => imageInputRef.current?.click()}
                        className="px-2.5 py-1 rounded-lg text-[11px] font-semibold surface-glass-base border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--primary)] transition-colors flex items-center gap-1"
                        title="Upload photo of handwritten notes or diagram"
                      >
                        <ImagePlus size={12} /> Add Photo
                      </button>
                      <input
                        ref={imageInputRef}
                        type="file"
                        accept="image/*"
                        multiple
                        className="hidden"
                        onChange={(e) => handleImageUpload(current.id, e)}
                      />
                    </div>
                  )}
                </div>

                <p className="text-base leading-relaxed whitespace-pre-wrap font-medium">{current.text}</p>

                {current.options ? (
                  <div className="grid gap-2">
                    {Object.entries(current.options)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([key, value]) => {
                        const numKey = LETTER_TO_NUM[key.toUpperCase()] ?? key;
                        const selected = answers[current.id]?.option_key === key || answers[current.id]?.option_key === numKey;
                        return (
                          <button
                            key={key}
                            onClick={() => setAnswer(current.id, { option_key: key })}
                            className={`text-left px-4 py-2.5 rounded-xl border text-sm transition-all flex items-start gap-2.5 ${
                              selected
                                ? "border-[var(--primary)] bg-[var(--accent)] font-semibold"
                                : "border-gray-200 dark:border-gray-600 hover:border-[var(--primary)]"
                            }`}
                          >
                            <span className={`font-mono font-bold px-1.5 py-0.5 rounded text-xs shrink-0 ${selected ? "bg-[var(--primary)] text-white" : "bg-gray-100 dark:bg-gray-700 text-gray-500"}`}>
                              {LETTER_TO_NUM[key] ? `(${LETTER_TO_NUM[key]}) ${key}` : key}
                            </span>
                            <span className="pt-0.5">{value}</span>
                          </button>
                        );
                      })}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {subParts.length > 1 && (
                      <div className="flex flex-wrap gap-1.5 p-1 rounded-xl surface-glass-base border border-[var(--border)]">
                        {subParts.map((sp) => (
                          <button
                            key={sp.label}
                            onClick={() => setActiveSubPart(sp.label)}
                            className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                              activeSubPart === sp.label
                                ? "bg-[var(--primary)] text-white shadow-sm"
                                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                            }`}
                          >
                            Part {sp.label}
                          </button>
                        ))}
                        <button
                          onClick={() => setActiveSubPart(null)}
                          className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                            activeSubPart === null
                              ? "bg-[var(--primary)] text-white shadow-sm"
                              : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                          }`}
                        >
                          All Parts (Full Answer)
                        </button>
                      </div>
                    )}

                    {subParts.length > 1 && activeSubPart ? (
                      <div className="space-y-1.5">
                        <p className="text-xs font-semibold text-[var(--primary)] flex items-center gap-1.5">
                          <span>Answering {activeSubPart}:</span>
                          <span className="text-[var(--muted-foreground)] font-normal text-[11px] truncate">
                            {subParts.find((s) => s.label === activeSubPart)?.title}
                          </span>
                        </p>
                        <textarea
                          rows={7}
                          value={answers[current.id]?.sub_answers?.[activeSubPart] ?? ""}
                          onChange={(e) => handleSubPartChange(current.id, activeSubPart, e.target.value)}
                          placeholder={`Write your answer for part ${activeSubPart} here…`}
                          className={`w-full p-4 text-sm bg-gray-50 dark:bg-[var(--secondary)] border border-[var(--border)] rounded-xl focus:ring-2 focus:ring-[var(--ring)] focus:outline-none ${codeMode ? "font-mono text-xs" : ""}`}
                        />
                      </div>
                    ) : (
                      <textarea
                        rows={7}
                        value={answers[current.id]?.answer_text ?? ""}
                        onChange={(e) => setAnswer(current.id, { answer_text: e.target.value })}
                        placeholder="Write your full answer here — AI Guru will grade it against the marking scheme…"
                        className={`w-full p-4 text-sm bg-gray-50 dark:bg-[var(--secondary)] border border-[var(--border)] rounded-xl focus:ring-2 focus:ring-[var(--ring)] focus:outline-none ${codeMode ? "font-mono text-xs" : ""}`}
                      />
                    )}

                    {currentImages.length > 0 && (
                      <div className="space-y-1.5 pt-1">
                        <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--muted-foreground)] flex items-center gap-1">
                          <Paperclip size={11} /> Attached Handwritten Work / Diagrams ({currentImages.length})
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {currentImages.map((img) => (
                            <div key={img.id} className="relative group rounded-xl overflow-hidden border border-[var(--border)] bg-black/10 w-24 h-24">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={img.previewUrl || `data:${img.mime};base64,${img.base64}`}
                                alt={img.filename}
                                className="w-full h-full object-cover"
                              />
                              <button
                                onClick={() => handleRemoveImage(current.id, img.id)}
                                className="absolute top-1 right-1 p-1 rounded-full bg-red-600/80 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                                title="Remove image"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex items-center justify-between pt-2">
                  <button
                    disabled={currentIdx === 0}
                    onClick={() => setCurrentIdx((i) => Math.max(0, i - 1))}
                    className="px-4 py-2 rounded-xl text-sm font-semibold border border-[var(--border)] disabled:opacity-40 flex items-center gap-1"
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
                            ? "bg-[var(--primary)] text-white"
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
                      className="px-4 py-2 rounded-xl text-sm font-semibold bg-[var(--primary)] text-white hover:brightness-110 flex items-center gap-1"
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
            <div className="bg-gradient-to-r from-[#E06D44] to-[#C8613C] rounded-2xl p-6 text-white flex items-center justify-between">
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
              <div key={r.question_id} className="bg-[var(--card)] rounded-2xl border border-[var(--border)] p-5 space-y-2">
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
                      <span className="text-[var(--muted-foreground)]">â€”</span>
                    )}
                    <span className="font-mono">
                      {r.awarded}/{r.max_marks}
                    </span>
                  </span>
                </div>
                {r.feedback && <p className="text-sm text-[var(--muted-foreground)]">{r.feedback}</p>}
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
              className="w-full py-3 rounded-xl border border-[var(--border)] font-bold text-sm hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              Take Another Paper
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
