// Framework-free chat store powering the FloatingGuru widget.
//
// Owns exactly one UnifiedWSClient (same-origin /api/v1/ws, cookie auth,
// heartbeat + reconnect built in) and exposes a tiny subscribe/snapshot
// surface that maps 1:1 onto React's useSyncExternalStore.
//
// Wire contract per turn:
//   { type: "start_turn", content, capability: "chat", session_id, language }
// inbound StreamEvents are folded into the message list ('content' deltas,
// 'tool_call'/'observation' as subtle "[tool] name" system lines, 'done' /
// 'error' finalize the turn).

import {
  UnifiedWSClient,
  type StreamEvent,
} from "@/lib/unified-ws";

export const FLOATING_SESSION_KEY = "aiguru.floating.sessionId";

export type FloatingChatRole = "user" | "assistant" | "system";

export interface FloatingChatMessage {
  id: string;
  role: FloatingChatRole;
  content: string;
  /** Assistant placeholder still receiving deltas. */
  streaming?: boolean;
  /** Terminal failure — rendered with error styling. */
  error?: boolean;
  ts: number;
}

export type FloatingChatStatus = "idle" | "connecting" | "streaming";

export interface FloatingChatSnapshot {
  messages: FloatingChatMessage[];
  status: FloatingChatStatus;
}

export interface FloatingChatStoreLike {
  subscribe(listener: (snapshot: FloatingChatSnapshot) => void): () => void;
  getSnapshot(): FloatingChatSnapshot;
  send(text: string, contextPrefix?: string): void;
  cancel(): void;
  reset(): void;
}

/** Referentially stable snapshot for useSyncExternalStore's server pass. */
export const FLOATING_EMPTY_SNAPSHOT: FloatingChatSnapshot = {
  messages: [],
  status: "idle",
};

type Listener = (snapshot: FloatingChatSnapshot) => void;

const DISCONNECT_IDLE_DELAY_MS = 5_000;

function uuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function loadSessionId(): string {
  if (typeof window === "undefined") return `floating-${uuid()}`;
  try {
    const stored = window.localStorage.getItem(FLOATING_SESSION_KEY);
    if (stored && stored.startsWith("floating-")) return stored;
    const fresh = `floating-${uuid()}`;
    window.localStorage.setItem(FLOATING_SESSION_KEY, fresh);
    return fresh;
  } catch {
    return `floating-${uuid()}`;
  }
}

function toolLabel(event: StreamEvent): string {
  const meta = event.metadata as
    | { tool?: unknown; name?: unknown; tool_name?: unknown; observation?: unknown }
    | undefined;
  const raw =
    meta?.tool ?? meta?.tool_name ?? meta?.name ?? event.stage ?? event.source;
  const label = String(raw ?? "").trim();
  return label || "tool";
}

export class FloatingChatStore implements FloatingChatStoreLike {
  private listeners = new Set<Listener>();
  private snapshot: FloatingChatSnapshot = { messages: [], status: "idle" };
  private client: UnifiedWSClient | null = null;
  private turnId: string | null = null;
  private counter = 0;
  private disconnectTimer: ReturnType<typeof setTimeout> | null = null;

  readonly sessionId: string;

  constructor(sessionId?: string) {
    this.sessionId = sessionId ?? loadSessionId();
  }

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): FloatingChatSnapshot => this.snapshot;

  send = (text: string, contextPrefix?: string): void => {
    const trimmed = text.trim();
    if (!trimmed || this.snapshot.status !== "idle") return;

    this.clearDisconnectTimer();
    const now = Date.now();
    const userMessage: FloatingChatMessage = {
      id: this.nextId("u"),
      role: "user",
      content: trimmed,
      ts: now,
    };
    const assistantMessage: FloatingChatMessage = {
      id: this.nextId("a"),
      role: "assistant",
      content: "",
      streaming: true,
      ts: now,
    };
    this.emit({
      messages: [...this.snapshot.messages, userMessage, assistantMessage],
      status: "connecting",
    });

    this.getClient().send({
      type: "start_turn",
      content: contextPrefix ? `${contextPrefix}\n\n${trimmed}` : trimmed,
      capability: "chat",
      session_id: this.sessionId,
      language: "en",
    });
  };

  cancel = (): void => {
    // Best-effort wire cancel; local finalize happens regardless so the UI
    // never wedges on a dead socket.
    if (this.client?.connected && this.turnId) {
      try {
        this.client.send({ type: "cancel_turn", turn_id: this.turnId });
      } catch {
        /* socket may be mid-close */
      }
    }
    this.finalizeLastAssistant((message) =>
      message.content.trim()
        ? message
        : { ...message, content: "_Cancelled._" },
    );
    this.emit({ status: "idle" });
    this.turnId = null;
    this.scheduleDisconnect();
  };

  reset = (): void => {
    this.clearDisconnectTimer();
    if (this.snapshot.status !== "idle") {
      this.finalizeLastAssistant(null);
    }
    this.turnId = null;
    this.emit({ messages: [], status: "idle" });
    this.scheduleDisconnect();
  };

  destroy(): void {
    this.clearDisconnectTimer();
    for (const listener of this.listeners) {
      this.listeners.delete(listener);
    }
    this.client?.disconnect();
    this.client = null;
  }

  // ---- internals ----

  private getClient(): UnifiedWSClient {
    if (!this.client) {
      this.client = new UnifiedWSClient(
        (event) => this.handleEvent(event),
        () => this.handleConnectionLost(),
      );
    }
    if (!this.client.connected) this.client.connect();
    return this.client;
  }

  private handleEvent(event: StreamEvent): void {
    if (event.turn_id) this.turnId = event.turn_id;
    switch (event.type) {
      case "content": {
        const delta = typeof event.content === "string" ? event.content : "";
        if (delta) {
          this.patchLastAssistant((message) => ({
            ...message,
            content: message.content + delta,
          }));
        }
        if (this.snapshot.status === "connecting") {
          this.emit({ status: "streaming" });
        }
        break;
      }
      case "thinking":
      case "progress":
        if (this.snapshot.status === "connecting") {
          this.emit({ status: "streaming" });
        }
        break;
      case "tool_call":
      case "observation": {
        const label = `[tool] ${toolLabel(event)}`;
        const messages = this.snapshot.messages;
        const last = messages[messages.length - 1];
        if (last && last.role === "system" && last.content === label) break;
        const systemLine: FloatingChatMessage = {
          id: this.nextId("s"),
          role: "system",
          content: label,
          ts: Date.now(),
        };
        this.emit({
          messages: [...messages, systemLine],
          status: "streaming",
        });
        break;
      }
      case "done":
        this.finalizeLastAssistant(null);
        this.emit({ status: "idle" });
        this.turnId = null;
        this.scheduleDisconnect();
        break;
      case "error": {
        const detail =
          typeof event.content === "string" ? event.content.trim() : "";
        const finalized = this.finalizeLastAssistant((message) => ({
          ...message,
          error: true,
          content: message.content.trim()
            ? message.content
            : detail || "Something went wrong. Please try again.",
        }));
        if (finalized) {
          this.emit({ status: "idle" });
          this.scheduleDisconnect();
        }
        break;
      }
      default:
        break;
    }
  }

  private handleConnectionLost(): void {
    if (this.snapshot.status === "idle") return;
    this.finalizeLastAssistant((message) => ({
      ...message,
      error: true,
      content: message.content.trim()
        ? message.content
        : "Connection lost while generating. Please retry.",
    }));
    this.emit({ status: "idle" });
    this.turnId = null;
  }

  /** Patch the trailing streaming assistant message; returns false if none. */
  private patchLastAssistant(
    patch: (message: FloatingChatMessage) => FloatingChatMessage,
  ): boolean {
    const messages = this.snapshot.messages;
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant" || !last.streaming) return false;
    this.emit({ messages: [...messages.slice(0, -1), patch(last)] });
    return true;
  }

  private finalizeLastAssistant(
    transform: ((message: FloatingChatMessage) => FloatingChatMessage) | null,
  ): boolean {
    return this.patchLastAssistant((message) => {
      const stopped = { ...message, streaming: false };
      return transform ? transform(stopped) : stopped;
    });
  }

  private emit(patch: Partial<FloatingChatSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of [...this.listeners]) {
      try {
        listener(this.snapshot);
      } catch {
        /* a broken subscriber must not break the stream */
      }
    }
  }

  private nextId(prefix: string): string {
    this.counter += 1;
    return `${prefix}${this.counter}-${Date.now().toString(36)}`;
  }

  private scheduleDisconnect(): void {
    this.clearDisconnectTimer();
    this.disconnectTimer = setTimeout(() => {
      this.disconnectTimer = null;
      this.client?.disconnect();
    }, DISCONNECT_IDLE_DELAY_MS);
  }

  private clearDisconnectTimer(): void {
    if (this.disconnectTimer) {
      clearTimeout(this.disconnectTimer);
      this.disconnectTimer = null;
    }
  }
}

let singleton: FloatingChatStore | null = null;

/** Process-wide store (one WS client per tab). */
export function getFloatingChatStore(): FloatingChatStore {
  if (!singleton) singleton = new FloatingChatStore();
  return singleton;
}
