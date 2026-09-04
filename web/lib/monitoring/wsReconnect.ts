/**
 * Shared capped-exponential-backoff WebSocket helper.
 * Extracted from the duplicated reconnect logic in VisionPipeline + TelemetrySocket.
 */

export interface ReconnectOptions {
  /** Build a fresh WebSocket on each (re)connect attempt. */
  create: () => WebSocket;
  /** Called when the socket opens (backoff resets). */
  onOpen?: (ws: WebSocket) => void;
  /** Called on each message. */
  onMessage?: (evt: MessageEvent, ws: WebSocket) => void;
  /** Connection-state changes (true = OPEN). */
  onState?: (connected: boolean) => void;
  baseMs?: number;
  maxMs?: number;
}

export class WsReconnect {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private backoffMs: number;
  private running = false;

  constructor(private opts: ReconnectOptions) {
    this.backoffMs = opts.baseMs ?? 1000;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.open();
  }

  stop(): void {
    this.running = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
    this.opts.onState?.(false);
  }

  get socket(): WebSocket | null {
    return this.ws;
  }

  send(payload: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private open(): void {
    const ws = this.opts.create();
    ws.onopen = () => {
      if (this.ws === ws) this.backoffMs = this.opts.baseMs ?? 1000;
      this.opts.onState?.(true);
      this.opts.onOpen?.(ws);
    };
    ws.onmessage = (evt) => {
      try {
        this.opts.onMessage?.(evt, ws);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // superseded
      this.ws = null;
      this.opts.onState?.(false);
      if (!this.running) return;
      const delay = this.backoffMs;
      this.backoffMs = Math.min(this.backoffMs * 2, this.opts.maxMs ?? 15000);
      this.timer = setTimeout(() => {
        this.timer = null;
        if (this.running && !this.ws) this.open();
      }, delay);
    };
    this.ws = ws;
  }
}

export function monitoringWsUrl(sessionId: string, mode?: "browser"): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = `${proto}//${window.location.host}/api/v1/monitoring/session/${encodeURIComponent(sessionId)}`;
  return mode ? `${base}?mode=${mode}` : base;
}
