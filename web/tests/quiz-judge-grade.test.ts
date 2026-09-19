/**
 * Node tests for the quiz judge client (lib/quiz-judge.ts).
 *
 * Covers the machine-readable grade-frame contract:
 * - well-formed grade frames reach onGrade with verdict+score
 * - malformed grade frames (missing score) are ignored
 * - unparsable frames are ignored
 * - text frames still accumulate into onDone
 */

import test from "node:test";
import assert from "node:assert/strict";

import { startQuizJudge, type QuizJudgeGrade } from "../lib/quiz-judge";

// ------------------------------------------------------------------- harness

class FakeJudgeSocket {
  static CONNECTING = 0;
  static OPEN = 1;

  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  sent: string[] = [];
  closed = false;

  constructor(public url: string) {
    FakeJudgeSocket.instances.push(this);
  }

  static instances: Array<FakeJudgeSocket> = [];

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
  }

  emit(data: string): void {
    this.onmessage?.({ data });
  }
}

function installWsStub(): void {
  FakeJudgeSocket.instances = [];
  (globalThis as Record<string, unknown>).WebSocket = FakeJudgeSocket;
}

function restoreWs(): void {
  delete (globalThis as Record<string, unknown>).WebSocket;
}

function basePayload() {
  return {
    question: "2+2?",
    question_type: "choice",
    options: { A: "3", B: "4" },
    correct_answer: "B",
    explanation: "basic addition",
    user_answer: "B",
    user_answer_images: [],
    language: "en" as const,
  };
}

// --------------------------------------------------------------------- tests

test("grade frame reaches onGrade and text accumulates to onDone", () => {
  installWsStub();
  try {
    const chunks: string[] = [];
    const grades: QuizJudgeGrade[] = [];
    let done = "";
    const handle = startQuizJudge(basePayload(), {
      onChunk: (c) => chunks.push(c),
      onDone: (t) => {
        done = t;
      },
      onError: () => assert.fail("unexpected onError"),
      onGrade: (g) => grades.push(g),
    });

    const ws = FakeJudgeSocket.instances[0];
    assert.ok(ws, "expected a WebSocket to be opened");
    ws.onopen?.();
    assert.equal(ws.sent.length, 1);

    ws.emit(JSON.stringify({ type: "started" }));
    ws.emit(JSON.stringify({ type: "text", content: "Correct! " }));
    ws.emit(JSON.stringify({ type: "text", content: "Well done." }));
    ws.emit(JSON.stringify({ type: "grade", verdict: "correct", score: 1 }));
    ws.emit(JSON.stringify({ type: "done" }));

    assert.deepEqual(chunks, ["Correct! ", "Well done."]);
    assert.deepEqual(grades, [{ verdict: "correct", score: 1 }]);
    assert.equal(done, "Correct! Well done.");
    handle.close();
  } finally {
    restoreWs();
  }
});

test("malformed grade frames and garbage are ignored", () => {
  installWsStub();
  try {
    const grades: QuizJudgeGrade[] = [];
    const errors: string[] = [];
    const handle = startQuizJudge(basePayload(), {
      onChunk: () => {},
      onDone: () => {},
      onError: (m) => errors.push(m),
      onGrade: (g) => grades.push(g),
    });

    const ws = FakeJudgeSocket.instances[0];
    ws.onopen?.();
    ws.emit("not-json{{{");
    ws.emit(JSON.stringify({ type: "grade", verdict: "correct" })); // no score
    ws.emit(JSON.stringify({ type: "grade", score: 0.5 })); // no verdict
    ws.emit(JSON.stringify({ type: "grade", verdict: "partial", score: 0.5 }));
    ws.emit(JSON.stringify({ type: "done" }));

    assert.deepEqual(grades, [{ verdict: "partial", score: 0.5 }]);
    assert.deepEqual(errors, []);
    handle.close();
  } finally {
    restoreWs();
  }
});
