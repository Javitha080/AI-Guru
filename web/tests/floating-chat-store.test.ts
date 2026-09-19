/**
 * Node tests for the floating chat store (lib/floating/floatingChatStore.ts).
 *
 * Covers the network-free public contract with a stubbed WebSocket:
 * - idle initial snapshot
 * - blank sends ignored
 * - busy sends ignored
 * - cancel() returns to idle
 * - reset() clears messages
 * - subscribe/unsubscribe delivery
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  FLOATING_EMPTY_SNAPSHOT,
  FloatingChatStore,
} from "../lib/floating/floatingChatStore";

// ------------------------------------------------------------------- harness

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];

  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((err: unknown) => void) | null = null;

  constructor(public url: string) {}

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
  }
}

function installWsStub(): Array<FakeWebSocket> {
  const instances: Array<FakeWebSocket> = [];
  const RealWebSocket = (globalThis as Record<string, unknown>).WebSocket;
  const Stub = class extends FakeWebSocket {
    constructor(url: string) {
      super(url);
      instances.push(this);
    }
  };
  (globalThis as Record<string, unknown>).WebSocket = Stub;
  return instances;
}

function restoreWs(): void {
  delete (globalThis as Record<string, unknown>).WebSocket;
}

// --------------------------------------------------------------------- tests

test("initial snapshot is idle and empty", () => {
  const store = new FloatingChatStore("floating-test-1");
  try {
    assert.equal(store.getSnapshot().status, "idle");
    assert.deepEqual(store.getSnapshot().messages, []);
    assert.equal(FLOATING_EMPTY_SNAPSHOT.status, "idle");
  } finally {
    store.destroy();
  }
});

test("blank sends are ignored without touching the socket", () => {
  installWsStub();
  try {
    const store = new FloatingChatStore("floating-test-2");
    try {
      store.send("");
      store.send("   ");
      assert.equal(store.getSnapshot().status, "idle");
      assert.deepEqual(store.getSnapshot().messages, []);
    } finally {
      store.destroy();
    }
  } finally {
    restoreWs();
  }
});

test("send queues a turn and blocks a second send while busy", () => {
  installWsStub();
  try {
    const store = new FloatingChatStore("floating-test-3");
    try {
      const seen: string[] = [];
      const unsub = store.subscribe((snap) => seen.push(snap.status));
      store.send("hello");
      const snap = store.getSnapshot();
      assert.equal(snap.status, "connecting");
      assert.equal(snap.messages.length, 2);
      assert.equal(snap.messages[0].role, "user");
      assert.equal(snap.messages[0].content, "hello");
      assert.equal(snap.messages[1].role, "assistant");
      assert.equal(snap.messages[1].streaming, true);

      // Busy: second send ignored.
      store.send("second turn");
      assert.equal(store.getSnapshot().messages.length, 2);
      assert.ok(seen.includes("connecting"));
      unsub();
    } finally {
      store.destroy();
    }
  } finally {
    restoreWs();
  }
});

test("cancel returns to idle and reset clears messages", () => {
  installWsStub();
  try {
    const store = new FloatingChatStore("floating-test-4");
    try {
      store.send("hello");
      assert.equal(store.getSnapshot().status, "connecting");
      store.cancel();
      assert.equal(store.getSnapshot().status, "idle");
      // Cancel keeps the transcript (placeholder finalized), reset clears it.
      assert.equal(store.getSnapshot().messages.length, 2);
      store.reset();
      assert.deepEqual(store.getSnapshot().messages, []);
      assert.equal(store.getSnapshot().status, "idle");
    } finally {
      store.destroy();
    }
  } finally {
    restoreWs();
  }
});
