// Cross-window state mirroring for the FloatingGuru Document-PiP detach.
//
// Contract:
//   - BroadcastChannel name: "aiguru-floating"
//   - Every frame is tagged with a unique `from` instance id; receivers drop
//     their own echoes, so no feedback loops.
//   - "state" frames carry the full snapshot — replace-on-receive,
//     last-write-wins.
//   - Control frames ("send" / "cancel" / "reset" / "popback" / "hello")
//     let a mirror-only window (the PiP panel) drive the owner's real store.

import type {
  FloatingChatSnapshot,
  FloatingChatStoreLike,
} from "./floatingChatStore";

export const FLOATING_CHANNEL_NAME = "aiguru-floating";

interface WireBase {
  v: 1;
  from: string;
}

export interface WireStateMessage extends WireBase {
  kind: "state";
  seq: number;
  snapshot: FloatingChatSnapshot;
}

export interface WireSendControl extends WireBase {
  kind: "send";
  text: string;
  contextPrefix?: string;
}

export interface WireCancelControl extends WireBase {
  kind: "cancel";
}

export interface WireResetControl extends WireBase {
  kind: "reset";
}

export interface WireHelloControl extends WireBase {
  kind: "hello";
}

export interface WirePopBackControl extends WireBase {
  kind: "popback";
}

export type WireMessage =
  | WireStateMessage
  | WireSendControl
  | WireCancelControl
  | WireResetControl
  | WireHelloControl
  | WirePopBackControl;

export type FloatingChannelHandler = (message: WireMessage) => void;

function instanceId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function isWireMessage(value: unknown): value is WireMessage {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { v?: unknown; from?: unknown; kind?: unknown };
  return (
    candidate.v === 1 &&
    typeof candidate.from === "string" &&
    typeof candidate.kind === "string"
  );
}

/** Thin, echo-safe wrapper around BroadcastChannel. */
export class FloatingChannel {
  readonly id = instanceId();
  private channel: BroadcastChannel | null = null;
  private handler: FloatingChannelHandler | null = null;
  private seq = 0;

  constructor(name: string = FLOATING_CHANNEL_NAME) {
    if (typeof BroadcastChannel !== "undefined") {
      try {
        this.channel = new BroadcastChannel(name);
        this.channel.onmessage = (event: MessageEvent) => {
          const data: unknown = event.data;
          if (!isWireMessage(data)) return;
          // Echo suppression: never process our own frames.
          if (data.from === this.id) return;
          this.handler?.(data);
        };
      } catch {
        this.channel = null;
      }
    }
  }

  get active(): boolean {
    return this.channel !== null;
  }

  onMessage(handler: FloatingChannelHandler): void {
    this.handler = handler;
  }

  publishState(snapshot: FloatingChatSnapshot): void {
    this.seq += 1;
    this.post({ kind: "state", seq: this.seq, snapshot });
  }

  sendControl(
    control:
      | Omit<WireSendControl, "v" | "from">
      | Omit<WireCancelControl, "v" | "from">
      | Omit<WireResetControl, "v" | "from">
      | Omit<WireHelloControl, "v" | "from">
      | Omit<WirePopBackControl, "v" | "from">,
  ): void {
    this.post(control);
  }

  close(): void {
    this.handler = null;
    if (this.channel) {
      this.channel.onmessage = null;
      this.channel.close();
      this.channel = null;
    }
  }

  private post(
    message:
      | Omit<WireStateMessage, "v" | "from">
      | Omit<WireSendControl, "v" | "from">
      | Omit<WireCancelControl, "v" | "from">
      | Omit<WireResetControl, "v" | "from">
      | Omit<WireHelloControl, "v" | "from">
      | Omit<WirePopBackControl, "v" | "from">,
  ): void {
    if (!this.channel) return;
    try {
      this.channel.postMessage({ v: 1 as const, from: this.id, ...message });
    } catch {
      /* structured-clone failure should never break the caller */
    }
  }
}

const EMPTY_SNAPSHOT: FloatingChatSnapshot = { messages: [], status: "idle" };

/**
 * A FloatingChatStoreLike that holds no transport of its own — it renders
 * whatever state the owner publishes and relays user actions back over the
 * channel. Used by the panel instance living inside the PiP window.
 */
export class FloatingMirrorStore implements FloatingChatStoreLike {
  private listeners = new Set<(snapshot: FloatingChatSnapshot) => void>();
  private snapshot: FloatingChatSnapshot = EMPTY_SNAPSHOT;

  constructor(private readonly channel: FloatingChannel) {
    this.channel.onMessage((message) => {
      if (message.kind === "state") {
        this.setSnapshot(message.snapshot);
      }
      // Other control kinds are addressed to the owner, not to mirrors.
    });
    // Ask any live owner for its current state so we don't flash empty.
    this.channel.sendControl({ kind: "hello" });
  }

  private setSnapshot(snapshot: FloatingChatSnapshot): void {
    this.snapshot = snapshot;
    for (const listener of this.listeners) listener(this.snapshot);
  }

  subscribe = (
    listener: (snapshot: FloatingChatSnapshot) => void,
  ): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): FloatingChatSnapshot => this.snapshot;

  send = (text: string, contextPrefix?: string): void => {
    this.channel.sendControl({
      kind: "send",
      text,
      ...(contextPrefix ? { contextPrefix } : {}),
    });
  };

  cancel = (): void => {
    this.channel.sendControl({ kind: "cancel" });
  };

  reset = (): void => {
    this.channel.sendControl({ kind: "reset" });
  };
}
