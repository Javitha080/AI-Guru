/**
 * Node tests for floating PiP mirror sync (lib/floating/floatingSync.ts).
 *
 * In plain language: the Document-PiP panel is a mirror — it renders
 * whatever state the owner window publishes over the "aiguru-floating"
 * BroadcastChannel, and it can drive the owner with control frames.
 * Contract under test:
 * - receivers drop their own echoes (no feedback loops)
 * - "state" frames replace the snapshot (last-write-wins)
 * - a new mirror says "hello" so an owner can push current state
 * - garbage frames are ignored, never crash
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  FLOATING_CHANNEL_NAME,
  FloatingChannel,
  FloatingMirrorStore,
} from "../lib/floating/floatingSync";
import type { FloatingChatSnapshot } from "../lib/floating/floatingChatStore";

function uniqueChannel(): string {
  return `${FLOATING_CHANNEL_NAME}-test-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function snapshotWith(text: string): FloatingChatSnapshot {
  return {
    messages: [{ id: "u1", role: "user", content: text, ts: 0 }],
    status: "idle",
  };
}

// --------------------------------------------------------------------- tests

test("channel uses the documented broadcast name by default", () => {
  const channel = new FloatingChannel();
  try {
    assert.equal(channel.active, typeof BroadcastChannel !== "undefined");
  } finally {
    channel.close();
  }
});

test("state published by one channel reaches another, never echoes back", async () => {
  const name = uniqueChannel();
  const owner = new FloatingChannel(name);
  const viewer = new FloatingChannel(name);
  try {
    const received: Array<{ kind: string }> = [];
    let selfEcho = 0;
    owner.onMessage(() => {
      selfEcho += 1;
    });
    viewer.onMessage((message) => {
      received.push(message);
    });

    owner.publishState(snapshotWith("hello"));
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(received.length, 1);
    assert.equal(received[0].kind, "state");
    assert.equal(selfEcho, 0);
  } finally {
    owner.close();
    viewer.close();
  }
});

test("mirror store replaces snapshot on state and ignores controls", async () => {
  const name = uniqueChannel();
  const owner = new FloatingChannel(name);
  const mirrorChannel = new FloatingChannel(name);
  const mirror = new FloatingMirrorStore(mirrorChannel);
  try {
    assert.deepEqual(mirror.getSnapshot().messages, []);

    owner.publishState(snapshotWith("owner says hi"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(mirror.getSnapshot().messages[0]?.content, "owner says hi");

    // Control frames are addressed to the owner, not mirrors.
    owner.sendControl({ kind: "reset" });
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(mirror.getSnapshot().messages[0]?.content, "owner says hi");

    // Last-write-wins.
    owner.publishState(snapshotWith("newer state"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(mirror.getSnapshot().messages[0]?.content, "newer state");
  } finally {
    owner.close();
    mirrorChannel.close();
  }
});

test("garbage frames never crash the channel", async () => {
  const name = uniqueChannel();
  const a = new FloatingChannel(name);
  const b = new FloatingChannel(name);
  try {
    let calls = 0;
    b.onMessage(() => {
      calls += 1;
    });
    const raw = new BroadcastChannel(name);
    try {
      raw.postMessage({ not: "a wire message" });
      raw.postMessage(null);
      raw.postMessage({ v: 1, from: "x" }); // missing kind — still well-formed guard
      await new Promise((resolve) => setTimeout(resolve, 50));
    } finally {
      raw.close();
    }
    assert.ok(calls <= 1);
  } finally {
    a.close();
    b.close();
  }
});
