"use client";

/**
 * Paper-Bank API client — typed wrappers over /api/v1/paper_bank/*.
 * Cookie-authenticated same-origin fetches via the Next.js proxy.
 */

export interface BankPartState {
  exam_id: string;
  bank_paper_id?: string;
  paper_no: number;
  title: string;
  status: "created" | "active" | "review" | "submitted" | "graded";
  phase?: string;
  time_up?: boolean;
  remaining_seconds: number | null;
  review_ends_at?: number | null;
  addon_seconds_used?: number;
  xp_multiplier?: number;
  duration_seconds?: number;
}

export interface SittingState {
  sitting_id: string;
  server_now: number;
  parts: BankPartState[];
  all_graded: boolean;
}

export interface StartResponse {
  sitting_id: string;
  group_key: string;
  title: string;
  parts: Array<{
    exam_id: string;
    bank_paper_id: string;
    paper_no: number;
    title: string;
    status: string;
    duration_seconds: number;
    started_at: number | null;
    ends_at: number | null;
  }>;
}

export interface BankQuestion {
  id: string;
  number: number;
  question_type: string;
  text: string;
  options: Record<string, string> | null;
  marks: number;
  reference_answer?: string | null;
  explanation?: string | null;
}

export interface BankPaperDetail {
  bank_paper_id: string;
  group_key: string;
  paper_no: number;
  grade: number;
  subject: string;
  year: number;
  medium: string;
  paper_type: string;
  default_duration_seconds: number;
  has_scheme_keys: boolean;
  paper: {
    exam_id: string;
    title: string;
    total_marks: number;
    mcq_count: number;
    essay_count: number;
    question_count: number;
    questions: BankQuestion[];
  };
}

export interface CatalogRow {
  id: string;
  group_key: string;
  paper_no: number;
  grade: number;
  subject: string;
  year: number;
  medium: string;
  paper_type: string;
  title: string;
  question_count: number;
  mcq_count: number;
  essay_count: number;
  total_marks: number;
  default_duration_seconds: number;
}

export interface ResultQuestion {
  question_id: string;
  number: number;
  question_type: string;
  text: string;
  options: Record<string, string> | null;
  answer_text: string;
  option_key: string;
  reference_answer: string | null;
  explanation: string | null;
  awarded: number;
  max_marks: number;
  verdict: string;
  feedback: string;
  graded: boolean;
}

export interface SittingResult {
  sitting_id: string;
  parts: Array<{
    exam_id: string;
    paper_no: number;
    title: string;
    status: string;
    score: number;
    max_marks: number;
    duration_taken_seconds: number | null;
    addon_seconds_used: number;
    xp_multiplier: number;
    questions: ResultQuestion[];
  }>;
  total_score: number;
  total_max_marks: number;
  pct: number | null;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = String(res.status);
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : detail;
    } catch {
      /* keep status code */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const papersApi = {
  facets: () =>
    fetch("/api/v1/paper_bank/facets").then((r) => jsonOrThrow<{
      subjects: string[];
      grades: number[];
      years: number[];
      mediums: string[];
    }>(r)),

  catalog: (params: { subject?: string; grade?: number; year?: number; medium?: string }) => {
    const q = new URLSearchParams();
    if (params.subject) q.set("subject", params.subject);
    if (params.grade) q.set("grade", String(params.grade));
    if (params.year) q.set("year", String(params.year));
    if (params.medium) q.set("medium", params.medium);
    return fetch(`/api/v1/paper_bank/catalog?${q.toString()}`).then((r) =>
      jsonOrThrow<{ papers: CatalogRow[]; count: number }>(r)
    );
  },

  getPaper: (bankPaperId: string) =>
    fetch(`/api/v1/paper_bank/${encodeURIComponent(bankPaperId)}`).then((r) =>
      jsonOrThrow<BankPaperDetail>(r)
    ),

  start: (bankPaperId: string, studentId = "student-primary") =>
    fetch(`/api/v1/paper_bank/${encodeURIComponent(bankPaperId)}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_id: studentId }),
    }).then((r) => jsonOrThrow<StartResponse>(r)),

  state: (sittingId: string) =>
    fetch(`/api/v1/paper_bank/sittings/${encodeURIComponent(sittingId)}`).then((r) =>
      jsonOrThrow<SittingState>(r)
    ),

  saveDraft: (sittingId: string, examId: string, answers: AnswerMap) => {
    const list = Object.entries(answers).map(([question_id, a]) => ({
      question_id,
      option_key: a.option_key ?? "",
      answer_text: a.answer_text ?? "",
      images: a.images ?? [],
      sub_answers: a.sub_answers ?? {},
    }));
    return fetch(`/api/v1/paper_bank/sittings/${encodeURIComponent(sittingId)}/draft`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exam_id: examId, answers: list }),
    }).then((r) => jsonOrThrow<{ ok: boolean; saved: number }>(r));
  },

  addon: (sittingId: string, minutes: number) =>
    fetch(`/api/v1/paper_bank/sittings/${encodeURIComponent(sittingId)}/addon`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minutes }),
    }).then((r) => jsonOrThrow<{ ok: boolean; added_seconds: number; ends_at: number; xp_multiplier: number; purchases: number; xp_balance?: number }>(r)),

  submit: (
    sittingId: string,
    examId: string,
    answers: AnswerMap,
    studentId = "student-primary"
  ) => {
    const list = Object.entries(answers).map(([question_id, a]) => ({
      question_id,
      option_key: a.option_key ?? "",
      answer_text: a.answer_text ?? "",
      images: a.images ?? [],
      sub_answers: a.sub_answers ?? {},
    }));
    return fetch(`/api/v1/paper_bank/sittings/${encodeURIComponent(sittingId)}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exam_id: examId, student_id: studentId, answers: list }),
    }).then((r) => jsonOrThrow<SubmitResponse>(r));
  },

  result: (sittingId: string) =>
    fetch(`/api/v1/paper_bank/sittings/${encodeURIComponent(sittingId)}/result`).then((r) =>
      jsonOrThrow<SittingResult>(r)
    ),

  explain: (sittingId: string, examId: string, questionId: string) =>
    fetch(`/api/v1/paper_bank/sittings/${encodeURIComponent(sittingId)}/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exam_id: examId, question_id: questionId }),
    }).then((r) => jsonOrThrow<{ explanation: string }>(r)),

  mySessions: (studentId = "student-primary") =>
    fetch(
      `/api/v1/paper_bank/my-sessions?student_id=${encodeURIComponent(studentId)}`
    ).then((r) => jsonOrThrow<MySessionsResponse>(r)),
};

export interface AnswerImageItem {
  id: string;
  base64?: string | null;
  url?: string | null;
  filename: string;
  mime: string;
  previewUrl?: string | null;
}

export type AnswerItem = {
  option_key?: string;
  answer_text?: string;
  images?: AnswerImageItem[];
  sub_answers?: Record<string, string>;
};

export type AnswerMap = Record<string, AnswerItem>;

export interface SubmitResponse {
  total_score: number;
  total_marks: number;
  results: Array<{
    question_id: string;
    verdict: string;
    awarded: number;
    max_marks: number;
  }>;
  part: { exam_id: string; paper_no: number; status: string };
  next_part_started: { exam_id: string; paper_no: number; duration_seconds: number; ends_at: number } | null;
  xp_awarded: number | null;
  sitting_complete: boolean;
}

export interface MySessionsResponse {
  sittings: Array<{
    sitting_id: string;
    parts: Array<CatalogRow & {
      exam_id: string;
      status: string;
      awarded: number;
      max_marks: number;
      pct: number | null;
      started_at: number | null;
      submitted_at: number | null;
    }>;
  }>;
  single_parts: unknown[];
}
