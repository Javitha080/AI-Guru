/**
 * Slim WebSocket client for system-camera monitoring sessions.
 *
 * When the backend owns the webcam (Python CV engine), the study room has NO
 * local vision pipeline — it only opens this socket to receive
 * ``telemetry_update`` broadcasts and to send control messages
 * (ping keepalive, pause/resume). Reconnect logic mirrors VisionPipeline's
 * capped-exponential-backoff so a dropped socket never freezes the HUD.
 */

export interface TelemetrySocketOptions {
  sessionId: string;
  /** Called for every `telemetry_update` message from the backend engine. */
  onUpdate: (msg: Record<string, unknown>) => void;
  /** Connection-state changes (true = OPEN). */
  onState?: (connected: boolean) => void;
}

export class TelemetrySocket {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private backoffMs = 1000;
  private running = false;

  constructor(private opts: TelemetrySocketOptions) {}

  start(): void {
    if (this.running) return;
    this.running = true;
    this.open();
    this.pingTimer = setInterval(() => this.send({ type: "ping" }), 25_000);
  }

  stop(): void {
    this.running = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
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

  sendPause(): void {
    this.send({ type: "pause" });
  }

  sendResume(): void {
    this.send({ type: "resume" });
  }

  private send(payload: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private open(): void {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${proto}//${window.location.host}/api/v1/monitoring/session/${this.opts.sessionId}`
    );
    ws.onopen = () => {
      if (this.ws === ws) this.backoffMs = 1000;
      this.opts.onState?.(true);
    };
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === "telemetry_update") this.opts.onUpdate(msg);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // superseded by a newer socket
      this.ws = null;
      this.opts.onState?.(false);
      if (!this.running) return;
      const delay = this.backoffMs;
      this.backoffMs = Math.min(this.backoffMs * 2, 15000);
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        if (this.running && !this.ws) this.open();
      }, delay);
    };
    this.ws = ws;
  }
}
