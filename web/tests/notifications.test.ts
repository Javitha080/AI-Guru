/**
 * Node tests for app-wide notification pub-sub (lib/notifications.ts).
 *
 * Covers:
 * - default payload values (tone, duration, id)
 * - custom tone and duration options
 * - empty message guard
 * - multiple subscriber delivery
 * - unsubscribe cleanup
 * - error isolation across listeners
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  notify,
  subscribeNotifications,
  type Notification,
} from "../lib/notifications";

test("delivers notification with default options to subscriber", () => {
  const received: Notification[] = [];
  const unsubscribe = subscribeNotifications((n) => received.push(n));

  notify("Study session started!");

  assert.equal(received.length, 1);
  assert.equal(received[0].message, "Study session started!");
  assert.equal(received[0].tone, "info");
  assert.equal(received[0].durationMs, 4000);
  assert.ok(received[0].id > 0);

  unsubscribe();
});

test("supports custom tone and duration", () => {
  const received: Notification[] = [];
  const unsubscribe = subscribeNotifications((n) => received.push(n));

  notify("Phone detected!", { tone: "error", durationMs: 6000 });

  assert.equal(received.length, 1);
  assert.equal(received[0].message, "Phone detected!");
  assert.equal(received[0].tone, "error");
  assert.equal(received[0].durationMs, 6000);

  unsubscribe();
});

test("supports warning and success tones", () => {
  const received: Notification[] = [];
  const unsubscribe = subscribeNotifications((n) => received.push(n));

  notify("Looking away", { tone: "warning" });
  notify("Completed goal", { tone: "success" });

  assert.equal(received.length, 2);
  assert.equal(received[0].tone, "warning");
  assert.equal(received[1].tone, "success");

  unsubscribe();
});

test("ignores empty or blank string messages", () => {
  const received: Notification[] = [];
  const unsubscribe = subscribeNotifications((n) => received.push(n));

  notify("");

  assert.equal(received.length, 0);

  unsubscribe();
});

test("unsubscribing removes the listener", () => {
  const received: Notification[] = [];
  const unsubscribe = subscribeNotifications((n) => received.push(n));

  notify("Message 1");
  assert.equal(received.length, 1);

  unsubscribe();

  notify("Message 2");
  assert.equal(received.length, 1); // no new message
});

test("broadcasts to multiple subscribers concurrently", () => {
  const sub1: Notification[] = [];
  const sub2: Notification[] = [];
  const unsub1 = subscribeNotifications((n) => sub1.push(n));
  const unsub2 = subscribeNotifications((n) => sub2.push(n));

  notify("Broadcast notice");

  assert.equal(sub1.length, 1);
  assert.equal(sub2.length, 1);
  assert.equal(sub1[0].id, sub2[0].id);

  unsub1();
  unsub2();
});

test("isolates throwing listeners so other subscribers still receive notifications", () => {
  const received: Notification[] = [];
  const unsubBad = subscribeNotifications(() => {
    throw new Error("Simulated listener crash");
  });
  const unsubGood = subscribeNotifications((n) => received.push(n));

  assert.doesNotThrow(() => {
    notify("Resilient delivery");
  });

  assert.equal(received.length, 1);
  assert.equal(received[0].message, "Resilient delivery");

  unsubBad();
  unsubGood();
});
