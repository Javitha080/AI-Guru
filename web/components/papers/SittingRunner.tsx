"use client";

/**
 * Paper-Bank Sitting Runner.
 *
 * State machine: running → (time-up) review → graded → next part … → final report.
 * - Countdown syncs to the server clock (poll /sittings every 15 s, local 1 s tick).
 * - Draft autosave while a part is active or in review.
 * - Add-on time shop: XP-multiplier cost + minimum balance gate.
 * - Google-Forms-style reveal after each part; AI explain per wrong question.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlarmClockPlus, CheckCircle2, ChevronLeft, ChevronRight, CircleHelp,
  Clock, Code, Eye, FileText, ImagePlus, Loader2, Paperclip, Send, Sparkles,
  Trash2, XCircle,
} from "lucide-react";
import {
  AnswerImageItem, AnswerItem, AnswerMap, BankPaperDetail, papersApi,
  ResultQuestion, SittingResult, SittingState,
} from "@/lib/papers/paper-api";

type Phase = "loading" | "running" | "submitting" | "results";

const STUDENT_ID = "student-primary";
const POLL_MS = 15_000;
const AUTOSAVE_MS = 20_000;

function fmtClock(totalSeconds: number): string {
  const s = Math.max(0, totalSeconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
}

const NUM_TO_LETTER: Record<string, string> = { "1": "A", "2": "B", "3": "C", "4": "D", "5": "E" };
const LETTER_TO_NUM: Record<string, string> = { A: "1", B: "2", C: "3", D: "4", E: "5" };

/** Extract structured sub-questions e.g. (a), (b), (i), (ii), (1), (2). */
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

export default function SittingRunner({
  sittingId,
  parts: initialParts,
  onExit,
}: {
  sittingId: string;
  parts: Array<{ exam_id: string; bank_paper_id: string; paper_no: number; title: string }>;
  onExit: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState("");
  const [state, setState] = useState<SittingState | null>(null);
  const [currentNo, setCurrentNo] = useState<number>(initialParts[0]?.paper_no ?? 1);
  const [paper, setPaper] = useState<BankPaperDetail | null>(null);
  const [answers, setAnswers] = useState<AnswerMap>({});
  const [currentIdx, setCurrentIdx] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [showAddon, setShowAddon] = useState(false);
  const [addonMsg, setAddonMsg] = useState<string>("");
  const [finalResult, setFinalResult] = useState<SittingResult | null>(null);
  const [codeMode, setCodeMode] = useState(false);
  const [activeSubPart, setActiveSubPart] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const dirtyRef = useRef(false);

  const partsById = useMemo(() => new Map(initialParts.map((p) => [p.paper_no, p])), [initialParts]);
  const partMeta = partsById.get(currentNo);
  const livePart = state?.parts.find((p) => p.paper_no === currentNo) ?? null;
  const status = livePart?.status ?? "created";
  const questions = paper?.paper.questions ?? [];
  const current = questions[currentIdx];
  const isSinhalaMedium = paper?.medium === "sinhala";

  // Sub-parts detected in current question
  const subParts = useMemo(() => {
    if (!current || current.question_type === "choice") return [];
    return extractSubParts(current.text);
  }, [current]);

  // Sync active sub-part when question changes
  useEffect(() => {
    if (subParts.length > 0) {
      setActiveSubPart(subParts[0].label);
    } else {
      setActiveSubPart(null);
    }
  }, [subParts]);

  // ---- server-clock poll -------------------------------------------------
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const st = await papersApi.state(sittingId);
        if (!alive) return;
        setState(st);
        if (st.all_graded) {
          const res = await papersApi.result(sittingId);
          if (!alive) return;
          setFinalResult(res);
          setPhase("results");
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void tick();
    const iv = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(iv); };
  }, [sittingId]);

  // ---- local countdown ---------------------------------------------------
  useEffect(() => {
    if (phase !== "running" || !livePart) return;
    const target =
      livePart.status === "review"
        ? livePart.review_ends_at ?? null
        : livePart.status === "active"
          ? (livePart.remaining_seconds ?? 0)
          : null;
    if (target === null) { setSecondsLeft(null); return; }
    const base = livePart.status === "active" ? target : Math.round(target - Date.now() / 1000);
    setSecondsLeft(Math.max(0, base));
    const iv = setInterval(() => setSecondsLeft((s) => (s === null ? null : Math.max(0, s - 1))), 1000);
    return () => clearInterval(iv);
  }, [phase, livePart?.status, livePart?.remaining_seconds, livePart?.review_ends_at, livePart]);

  // ---- load current paper ------------------------------------------------
  useEffect(() => {
    if (phase === "results" || phase === "submitting") return;
    const meta = partsById.get(currentNo);
    if (!meta || paper?.bank_paper_id === meta.bank_paper_id) return;
    let alive = true;
    setPhase("loading");
    papersApi.getPaper(meta.bank_paper_id).then((p) => {
      if (!alive) return;
      setPaper(p);
      setCurrentIdx(0);
      setPhase("running");
    }).catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentNo, phase]);

  // ---- draft autosave ----------------------------------------------------
  useEffect(() => {
    if (!partMeta || !dirtyRef.current) return;
    if (status !== "active" && status !== "review") return;
    const iv = setInterval(() => {
      if (!dirtyRef.current) return;
      papersApi.saveDraft(sittingId, partMeta.exam_id, answers)
        .then(() => { dirtyRef.current = false; })
        .catch(() => {});
    }, AUTOSAVE_MS);
    return () => clearInterval(iv);
  }, [answers, partMeta, sittingId, status]);

  // ---- advance phases when server flips them ----------------------------
  const prevStatus = useRef(status);
  useEffect(() => {
    if (prevStatus.current !== "graded" && status === "graded" && phase === "running") {
      void handleSubmit(true);
    }
    prevStatus.current = status;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const setAnswer = useCallback((qid: string, patch: Partial<AnswerItem>) => {
    setAnswers((prev) => ({
      ...prev,
      [qid]: {
        ...prev[qid],
        ...patch,
      },
    }));
    dirtyRef.current = true;
  }, []);

  const handleSubPartChange = (qid: string, partLabel: string, text: string) => {
    const existing = answers[qid]?.sub_answers ?? {};
    const updated = { ...existing, [partLabel]: text };
    // Reconstruct full text from subparts
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
        const newImg: AnswerImageItem = {
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

  const handleSubmit = useCallback(async (auto = false) => {
    if (!partMeta) return;
    if (!auto) {
      const unanswered = questions.filter((q) => {
        const a = answers[q.id];
        return !a || (!a.option_key && !a.answer_text?.trim() && !(a.images && a.images.length > 0));
      }).length;
      if (unanswered > 0 && !window.confirm(`${unanswered} question(s) are blank. Submit anyway?`)) return;
    }
    setPhase("submitting");
    try {
      await papersApi.submit(sittingId, partMeta.exam_id, answers, STUDENT_ID);
      const st = await papersApi.state(sittingId);
      setState(st);
      if (st.all_graded) {
        setFinalResult(await papersApi.result(sittingId));
        setPhase("results");
        return;
      }
      const next = st.parts.find((p) => p.status !== "graded");
      setAnswers({});
      setCurrentNo(next?.paper_no ?? currentNo + 1);
      setPhase("loading");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("running");
    }
  }, [answers, currentNo, partMeta, questions, sittingId]);

  const buyAddon = async (minutes: number) => {
    setAddonMsg("");
    try {
      const r = await papersApi.addon(sittingId, minutes);
      setShowAddon(false);
      setSecondsLeft((s) => (s ?? 0) + Math.round(r.added_seconds));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setAddonMsg(msg.startsWith("insufficient_xp")
        ? `Not enough XP (balance ${msg.split(":")[1] ?? "0"}). Earn XP by finishing sessions and papers.`
        : msg);
    }
  };

  // ======================================================================
  if (phase === "results" && finalResult) {
    return <FinalReport result={finalResult} sittingId={sittingId} onExit={onExit} />;
  }

  if (phase === "loading" || !paper) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-[var(--muted-foreground)] gap-2">
        <Loader2 size={16} className="animate-spin" /> Preparing your paper…
        {error && <span className="text-red-400 ml-2">{error}</span>}
      </div>
    );
  }

  const isMcq = current?.question_type === "choice";
  const answeredCount = questions.filter((q) => {
    const a = answers[q.id];
    return a && (a.option_key || a.answer_text?.trim() || (a.images && a.images.length > 0));
  }).length;
  const currentImages = answers[current?.id]?.images ?? [];

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* HUD */}
      <div className="surface-glass-base mx-3 mt-3 rounded-2xl px-4 py-3 flex items-center justify-between gap-3 shrink-0 relative z-30">
        <div className="min-w-0">
          <h2 className="font-display font-bold text-sm truncate">{paper.paper.title}</h2>
          <p className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
            Paper {currentNo} · {answeredCount}/{questions.length} answered ·{" "}
            {status === "review" ? (
              <span className="text-[var(--amber)] font-bold">Double-check window — answers still editable</span>
            ) : status === "active" ? (
              "Timed run"
            ) : (
              "Graded"
            )}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {status === "active" && secondsLeft !== null && (
            <button
              onClick={() => setShowAddon(true)}
              className={`px-3 py-2 rounded-xl text-xs font-bold flex items-center gap-1.5 border transition-colors ${
                secondsLeft < 300
                  ? "bg-[var(--amber-glow)] text-[var(--amber)] border-[var(--amber)]/40 ember-dot"
                  : "surface-glass-base glow-ring hover:text-[var(--primary)]"
              }`}
              title="Buy extra time (costs final XP)"
            >
              <AlarmClockPlus size={14} /> Buy Time
            </button>
          )}
          {(status === "active" || status === "review") && secondsLeft !== null && (
            <span className={`font-mono font-bold text-lg tabular-nums ${secondsLeft < 300 ? "text-red-400" : "text-[var(--primary)]"}`}>
              {fmtClock(secondsLeft)}
            </span>
          )}
          {status === "review" && secondsLeft !== null && secondsLeft > 0 && (
            <button
              onClick={() => void handleSubmit()}
              disabled={phase === "submitting"}
              className="px-4 py-2 rounded-xl bg-[var(--primary)] text-white text-xs font-bold shadow-[0_6px_20px_var(--glow-primary)] disabled:opacity-50 flex items-center gap-1.5"
            >
              {phase === "submitting" ? <Loader2 size={14} className="animate-spin" /> : <Send size={13} />}
              Submit &amp; See Answers
            </button>
          )}
        </div>
      </div>

      {/* Review banner */}
      {status === "review" && (
        <div className="mx-3 mt-2 px-4 py-2.5 rounded-xl bg-[var(--amber-glow)]/50 border border-[var(--amber)]/30 text-xs text-[var(--amber)] flex items-center gap-2 shrink-0">
          <Clock size={13} />
          Time is up — use this free double-check window to revisit flagged answers. When it ends, the paper submits itself.
        </div>
      )}

      {/* Question */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        {current ? (
          <div className="max-w-3xl mx-auto space-y-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="w-9 h-9 rounded-xl bg-[var(--ember-0)] border border-[var(--glass-border)] flex items-center justify-center text-sm font-bold text-[var(--primary)] shrink-0">
                  {current.number}
                </span>
                <span className="text-[11px] px-2.5 py-0.5 rounded-full surface-glass-base text-[var(--muted-foreground)] uppercase tracking-wide font-semibold">
                  {isMcq ? `MCQ · ${Object.keys(current.options ?? {}).length} options` : "Structured Essay"}
                </span>
                <span className="text-[11px] text-[var(--muted-foreground)] font-mono">{current.marks} mark{current.marks === 1 ? "" : "s"}</span>
              </div>
              {!isMcq && (
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setCodeMode(!codeMode)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition-colors flex items-center gap-1 ${
                      codeMode
                        ? "bg-[var(--primary)] text-white border-transparent"
                        : "surface-glass-base border-[var(--glass-border)] text-[var(--muted-foreground)]"
                    }`}
                    title="Toggle code / monospaced font mode"
                  >
                    <Code size={12} /> Code mode
                  </button>
                  <button
                    onClick={() => imageInputRef.current?.click()}
                    className="px-2.5 py-1 rounded-lg text-[11px] font-semibold surface-glass-base border border-[var(--glass-border)] text-[var(--muted-foreground)] hover:text-[var(--primary)] transition-colors flex items-center gap-1"
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

            <p className="text-sm leading-relaxed whitespace-pre-wrap font-normal">{current.text}</p>

            {isMcq ? (
              <div className="space-y-2">
                {Object.entries(current.options ?? {}).map(([key, val]) => {
                  const numKey = LETTER_TO_NUM[key.toUpperCase()] ?? key;
                  const selected = answers[current.id]?.option_key === key || answers[current.id]?.option_key === numKey;
                  return (
                    <button
                      key={key}
                      onClick={() => setAnswer(current.id, { option_key: key })}
                      className={`w-full text-left p-3.5 rounded-xl border transition-all duration-150 flex items-start gap-3 group ${
                        selected
                          ? "border-[var(--primary)]/70 bg-[var(--ember-0)] shadow-[0_0_18px_var(--glow-primary)]"
                          : "border-[var(--glass-border)] surface-glass-base hover:border-[var(--ember-line)]"
                      }`}
                    >
                      <span className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 ${
                        selected ? "bg-[var(--primary)] text-white" : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                      }`}>
                        {isSinhalaMedium && NUM_TO_LETTER[key] ? `(${key})` : isSinhalaMedium && LETTER_TO_NUM[key] ? `(${LETTER_TO_NUM[key]})` : key}
                      </span>
                      <span className="text-sm leading-snug pt-0.5">{val}</span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="space-y-3">
                {/* Sub-parts tabs if multiple parts detected */}
                {subParts.length > 1 && (
                  <div className="flex flex-wrap gap-1.5 p-1 rounded-xl surface-glass-base border border-[var(--glass-border)]">
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

                {/* Text area input */}
                {subParts.length > 1 && activeSubPart ? (
                  <div className="space-y-1.5">
                    <p className="text-xs font-semibold text-[var(--primary)] flex items-center gap-1.5">
                      <span>Answering {activeSubPart}:</span>
                      <span className="text-[var(--muted-foreground)] font-normal text-[11px] truncate">
                        {subParts.find((s) => s.label === activeSubPart)?.title}
                      </span>
                    </p>
                    <textarea
                      value={answers[current.id]?.sub_answers?.[activeSubPart] ?? ""}
                      onChange={(e) => handleSubPartChange(current.id, activeSubPart, e.target.value)}
                      placeholder={`Write your answer for part ${activeSubPart} here…`}
                      rows={8}
                      className={`glass-input w-full p-4 text-sm leading-relaxed resize-y ${codeMode ? "font-mono text-xs" : ""}`}
                    />
                  </div>
                ) : (
                  <textarea
                    value={answers[current.id]?.answer_text ?? ""}
                    onChange={(e) => setAnswer(current.id, { answer_text: e.target.value })}
                    placeholder="Write your answer here — AI Guru will evaluate your steps against the marking guide…"
                    rows={10}
                    className={`glass-input w-full p-4 text-sm leading-relaxed resize-y ${codeMode ? "font-mono text-xs" : ""}`}
                  />
                )}

                {/* Attached handwritten images thumbnail row */}
                {currentImages.length > 0 && (
                  <div className="space-y-1.5 pt-1">
                    <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--muted-foreground)] flex items-center gap-1">
                      <Paperclip size={11} /> Attached Handwritten Work / Diagrams ({currentImages.length})
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {currentImages.map((img) => (
                        <div key={img.id} className="relative group rounded-xl overflow-hidden border border-[var(--glass-border)] bg-black/20 w-24 h-24">
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

            {/* Navigator */}
            <div className="pt-4 flex flex-wrap items-center gap-1.5">
              {questions.map((q, i) => {
                const done = (() => {
                  const a = answers[q.id];
                  return !!a && (!!a.option_key || !!a.answer_text?.trim() || !!(a.images && a.images.length > 0));
                })();
                return (
                  <button
                    key={q.id}
                    onClick={() => setCurrentIdx(i)}
                    className={`w-8 h-8 rounded-lg text-[11px] font-bold border transition-colors ${
                      i === currentIdx
                        ? "bg-[var(--primary)] text-white border-transparent"
                        : done
                          ? "bg-[var(--ember-0)] text-[var(--primary)] border-[var(--ember-line)]/40"
                          : "surface-glass-base border-[var(--glass-border)] text-[var(--muted-foreground)]"
                    }`}
                    title={`Question ${q.number}`}
                  >
                    {q.number}
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <p className="text-center text-sm text-[var(--muted-foreground)]">No questions in this paper.</p>
        )}
      </div>

      {/* Footer nav */}
      <div className="surface-glass-base mx-3 mb-3 rounded-2xl px-4 py-3 flex items-center justify-between shrink-0">
        <button onClick={() => setCurrentIdx((i) => Math.max(0, i - 1))} disabled={currentIdx === 0}
          className="px-3.5 py-2 rounded-xl surface-glass-base glow-ring text-xs font-bold disabled:opacity-40 flex items-center gap-1">
          <ChevronLeft size={14} /> Prev
        </button>
        <span className="text-[11px] text-[var(--muted-foreground)]">{currentIdx + 1} of {questions.length}</span>
        {currentIdx < questions.length - 1 ? (
          <button onClick={() => setCurrentIdx((i) => Math.min(questions.length - 1, i + 1))}
            className="px-3.5 py-2 rounded-xl surface-glass-base glow-ring text-xs font-bold flex items-center gap-1">
            Next <ChevronRight size={14} />
          </button>
        ) : (
          <button onClick={() => void handleSubmit()} disabled={phase === "submitting"}
            className="px-4 py-2 rounded-xl bg-[var(--primary)] text-white text-xs font-bold disabled:opacity-50 flex items-center gap-1.5">
            {phase === "submitting" ? <Loader2 size={14} className="animate-spin" /> : <Send size={13} />} Submit Part
          </button>
        )}
      </div>

      {/* Add-on shop */}
      {showAddon && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" role="dialog" aria-modal>
          <div className="bento-cell p-6 w-full max-w-md space-y-4">
            <h3 className="font-display font-bold flex items-center gap-2"><AlarmClockPlus size={17} className="text-[var(--primary)]" /> Buy Extra Time</h3>
            <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
              Every purchase lowers the XP this sitting will earn — like buying an energy refill with game money. Max {2} purchases per sitting.
            </p>
            <div className="grid grid-cols-3 gap-2">
              {[15, 30, 60].map((min, i) => (
                <button key={min} onClick={() => void buyAddon(min)}
                  className="bento-cell bento-cell--hover p-3 text-center">
                  <p className="text-lg font-extrabold text-[var(--primary)]">+{min}</p>
                  <p className="text-[10px] text-[var(--muted-foreground)]">min</p>
                  <p className="text-[10px] font-bold text-[var(--amber)] mt-1">XP ×{[0.9, 0.75, 0.6][i]}</p>
                </button>
              ))}
            </div>
            {addonMsg && <p className="text-xs text-red-400">{addonMsg}</p>}
            <button onClick={() => setShowAddon(false)} className="w-full py-2 rounded-xl surface-glass-base text-xs font-bold">Keep going without extra time</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ report */

function FinalReport({ result, sittingId, onExit }: { result: SittingResult; sittingId: string; onExit: () => void }) {
  const pct = result.pct ?? 0;
  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-5">
      <div className="max-w-3xl mx-auto space-y-5">
        <div className="bento-cell liquid-sheen p-6 text-center space-y-1.5">
          <p className="text-[11px] uppercase tracking-[0.22em] text-[var(--muted-foreground)]">Sitting complete</p>
          <p className="font-display text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-[var(--primary)] to-[var(--amber)]">
            {result.total_score} / {result.total_max_marks}
          </p>
          <p className="text-sm font-bold text-[var(--primary)]">{pct}%</p>
        </div>

        {result.parts.map((part) => (
          <div key={part.exam_id} className="bento-cell p-5 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-bold truncate">{part.title}</h3>
              <span className="text-xs font-mono text-[var(--primary)] shrink-0">{part.score}/{part.max_marks}</span>
            </div>
            <PartQuestions partExamId={part.exam_id} questions={part.questions} sittingId={sittingId} />
          </div>
        ))}

        <button onClick={onExit} className="glass-btn-primary w-full !rounded-xl justify-center">
          <Sparkles size={15} /> Back to Paper Bank
        </button>
      </div>
    </div>
  );
}

function PartQuestions({ questions, partExamId, sittingId }: {
  questions: ResultQuestion[]; partExamId: string; sittingId: string;
}) {
  const [openExpl, setOpenExpl] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string>("");

  const askAi = async (qid: string) => {
    setBusy(qid);
    try {
      const r = await papersApi.explain(sittingId, partExamId, qid);
      setOpenExpl((p) => ({ ...p, [qid]: r.explanation }));
    } catch (e) {
      setOpenExpl((p) => ({ ...p, [qid]: `AI explanation unavailable right now (${e instanceof Error ? e.message : e}).` }));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-2">
      {questions.map((q) => {
        const correct = q.verdict === "correct" || (q.awarded >= q.max_marks && q.max_marks > 0);
        const partial = q.verdict === "partial";
        return (
          <div key={q.question_id}
            className={`rounded-xl border p-3.5 space-y-2 ${
              correct ? "border-emerald-500/30 bg-emerald-500/5"
              : partial ? "border-[var(--amber)]/30 bg-[var(--amber-glow)]/40"
              : q.answer_text || q.option_key ? "border-red-500/30 bg-red-500/5"
              : "border-[var(--glass-border)] surface-glass-base"
            }`}>
            <div className="flex items-start justify-between gap-2">
              <p className="text-xs font-semibold leading-relaxed line-clamp-2">
                <span className="font-mono mr-1.5">{q.number}.</span>{q.text.slice(0, 160)}
              </p>
              <span className={`shrink-0 flex items-center gap-1 text-[11px] font-bold ${
                correct ? "text-emerald-400" : partial ? "text-[var(--amber)]" : "text-red-400"}`}>
                {correct ? <CheckCircle2 size={13} /> : partial || (!q.option_key && !q.answer_text) ? <CircleHelp size={13} /> : <XCircle size={13} />}
                {q.awarded}/{q.max_marks}
              </span>
            </div>
            <div className="text-[11px] space-y-0.5 text-[var(--muted-foreground)]">
              <p>Your answer: <span className="font-semibold text-[var(--foreground)]">{q.option_key || q.answer_text?.slice(0, 120) || "—"}</span></p>
              {q.reference_answer && (
                <p>Correct: <span className="font-semibold text-emerald-400">{q.reference_answer}</span></p>
              )}
            </div>
            {q.feedback && <p className="text-[11px] italic text-[var(--muted-foreground)]">{q.feedback}</p>}
            {(!correct || partial) && q.reference_answer && (
              <div className="space-y-1.5">
                {!openExpl[q.question_id] && (
                  <button onClick={() => void askAi(q.question_id)} disabled={busy === q.question_id}
                    className="px-3 py-1.5 rounded-lg bg-[var(--ember-0)] border border-[var(--ember-line)]/40 text-[11px] font-bold text-[var(--primary)] disabled:opacity-50 flex items-center gap-1.5">
                    {busy === q.question_id ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                    Ask AI Guru why
                  </button>
                )}
                {openExpl[q.question_id] && (
                  <p className="text-[11px] leading-relaxed p-2.5 rounded-lg surface-glass-base border border-[var(--glass-border)] whitespace-pre-wrap">
                    {openExpl[q.question_id]}
                  </p>
                )}
                {!openExpl[q.question_id] && q.explanation && (
                  <details className="text-[11px] text-[var(--muted-foreground)]">
                    <summary className="cursor-pointer select-none">Marking notes</summary>
                    <p className="mt-1 whitespace-pre-wrap">{q.explanation.slice(0, 800)}</p>
                  </details>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
