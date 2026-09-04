/**
 * Slim WebSocket client for system-camera monitoring sessions.
 *
 * When the backend owns the webcam (Python CV engine), the study room has NO
 * local vision pipeline — it only opens this socket to receive
 * ``telemetry_update`` broadcasts and to send control messages
 * (ping keepalive, pause/resume). Reconnect uses the shared WsReconnect
 * helper so a dropped socket never freezes the HUD.
 */

import { WsReconnect, monitoringWsUrl } from "./wsReconnect";

export interface TelemetrySocketOptions {
  sessionId: string;
  /** Called for every `telemetry_update` message from the backend engine. */
  onUpdate: (msg: Record<string, unknown>) => void;
  /** Connection-state changes (true = OPEN). */
  onState?: (connected: boolean) => void;
}

export class TelemetrySocket {
  private conn: WsReconnect | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private running = false;

  constructor(private opts: TelemetrySocketOptions) {}

  start(): void {
    if (this.running) return;
    this.running = true;
    const sessionId = this.opts.sessionId;
    this.conn = new WsReconnect({
      create: () => new WebSocket(monitoringWsUrl(sessionId)),
      onState: (ok) => this.opts.onState?.(ok),
      onMessage: (evt) => {
        try {
          const msg = JSON.parse((evt as MessageEvent).data);
          if (msg.type === "telemetry_update") this.opts.onUpdate(msg);
        } catch {
          /* ignore malformed frames */
        }
      },
    });
    this.conn.start();
    this.pingTimer = setInterval(() => this.send({ type: "ping" }), 25_000);
  }

  stop(): void {
    this.running = false;
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    this.conn?.stop();
    this.conn = null;
    this.opts.onState?.(false);
  }

  sendPause(): void {
    this.send({ type: "pause" });
  }

  sendResume(): void {
    this.send({ type: "resume" });
  }

  private send(payload: Record<string, unknown>): void {
    this.conn?.send(payload);
  }
}
