/**
 * AI Guru local vision pipeline.
 *
 * Runs MediaPipe FaceLandmarker fully on-device (WASM, GPU delegate with
 * CPU fallback) against a <video> element and:
 *   - maps landmarks into the exact groups the backend geometry engine
 *     expects (left_eye/right_eye/mouth/all_points + anchors),
 *   - computes brightness (0-1) and texture Laplacian variance,
 *   - throttles JPEG snapshots for encrypted-vault evidence,
 *   - optionally streams telemetry over WS /api/v1/monitoring/session/{id}.
 *
 * Zero cloud egress: models load from /mediapipe/* (vendored) or CDN;
 * no frame bytes ever leave the machine except the optional evidence
 * channel to the LOCAL backend.
 */

import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";

export type VisionState = "idle" | "loading" | "ready" | "error";

export interface LandmarkPoint {
  x: number;
  y: number;
  z: number;
}

export interface LandmarkGroups {
  left_eye: LandmarkPoint[];
  right_eye: LandmarkPoint[];
  mouth: LandmarkPoint[];
  all_points: LandmarkPoint[];
  nose_tip: LandmarkPoint;
  chin: LandmarkPoint;
  forehead: LandmarkPoint;
  left_cheek: LandmarkPoint;
  right_cheek: LandmarkPoint;
}

export interface TelemetryFrame {
  detected: boolean;
  confidence: number;
  brightness: number;
  bbox?: [number, number, number, number];
  landmarks?: LandmarkGroups;
  jpeg_b64?: string;
  /** Laplacian variance of the grayscale frame — in-session anti-spoof texture cue. */
  texture_laplacian_var?: number;
  timestamp?: number;
}

/** Compact ordered subsets — horizontal corners first, then lid pairs (EAR-friendly). */
const LEFT_EYE_IDX = [33, 133, 159, 145, 158, 153];
const RIGHT_EYE_IDX = [263, 362, 386, 374, 385, 380];
const MOUTH_IDX = [61, 291, 13, 14, 82, 87];
const NOSE_TIP_IDX = 1;
const CHIN_IDX = 152;
const FOREHEAD_IDX = 10;
const LEFT_CHEEK_IDX = 234;
const RIGHT_CHEEK_IDX = 454;

function pt(lm: { x: number; y: number; z: number } | undefined): LandmarkPoint {
  return lm ? { x: lm.x, y: lm.y, z: lm.z ?? 0 } : { x: 0.5, y: 0.5, z: 0 };
}

export function buildLandmarkGroups(face: readonly { x: number; y: number; z: number }[]): LandmarkGroups {
  const pick = (idxs: number[]) => idxs.map((i) => pt(face[i]));
  return {
    left_eye: pick(LEFT_EYE_IDX),
    right_eye: pick(RIGHT_EYE_IDX),
    mouth: pick(MOUTH_IDX),
    all_points: face.map(pt),
    nose_tip: pt(face[NOSE_TIP_IDX]),
    chin: pt(face[CHIN_IDX]),
    forehead: pt(face[FOREHEAD_IDX]),
    left_cheek: pt(face[LEFT_CHEEK_IDX]),
    right_cheek: pt(face[RIGHT_CHEEK_IDX]),
  };
}

export interface VisionPipelineOptions {
  video: HTMLVideoElement;
  /** When set, telemetry is streamed to the backend monitoring WS. */
  sessionId?: string;
  targetFps?: number;
  jpegQuality?: number;
  onTelemetry?: (frame: TelemetryFrame, remote?: Record<string, unknown>) => void;
  onState?: (state: VisionState, detail?: string) => void;
}

const LOCAL_WASM = "/mediapipe/wasm";
const CDN_WASM = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";
const LOCAL_MODEL = "/mediapipe/face_landmarker.task";
const CDN_MODEL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

export class VisionPipeline {
  private landmarker: FaceLandmarker | null = null;
  private ws: WebSocket | null = null;
  private wsReconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private wsBackoffMs = 1000;
  private rafId = 0;
  private lastTick = 0;
  private tickCount = 0;
  private running = false;
  private paused = false;
  private grayCanvas: HTMLCanvasElement | null = null;
  private snapCanvas: HTMLCanvasElement | null = null;

  /** Rolling landmark-group history for pre-flight liveness capture. */
  private landmarkHistory: LandmarkGroups[] = [];

  readonly recentRemote: Record<string, unknown>[] = [];
  targetFps: number;

  constructor(private opts: VisionPipelineOptions) {
    this.targetFps = opts.targetFps ?? 5;
  }

  // -------------------------------------------------------------- lifecycle

  async start(): Promise<void> {
    this.running = true;
    this.paused = false;
    this.opts.onState?.("loading");
    try {
      let wasmPath = LOCAL_WASM;
      let modelPath = LOCAL_MODEL;
      try {
        // Probe the vendored model once; fall back to CDN if missing.
        const probe = await fetch(LOCAL_MODEL, { method: "HEAD" });
        if (!probe.ok) {
          wasmPath = CDN_WASM;
          modelPath = CDN_MODEL;
        }
      } catch {
        wasmPath = CDN_WASM;
        modelPath = CDN_MODEL;
      }

      const fileset = await FilesetResolver.forVisionTasks(wasmPath);
      try {
        this.landmarker = await FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: modelPath, delegate: "GPU" },
          runningMode: "VIDEO",
          numFaces: 1,
        });
      } catch {
        // GPU delegate unavailable (common on low-end iGPUs) → CPU.
        this.landmarker = await FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: modelPath, delegate: "CPU" },
          runningMode: "VIDEO",
          numFaces: 1,
        });
      }

      if (this.opts.sessionId) this.openSocket(this.opts.sessionId);
      this.opts.onState?.("ready");
      this.loop();
    } catch (err) {
      console.warn("[vision] init failed", err);
      this.opts.onState?.("error", err instanceof Error ? err.message : String(err));
    }
  }

  stop(): void {
    this.running = false;
    this.paused = false;
    cancelAnimationFrame(this.rafId);
    if (this.wsReconnectTimer) {
      clearTimeout(this.wsReconnectTimer);
      this.wsReconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
    try {
      this.landmarker?.close();
    } catch {
      /* ignore */
    }
    this.landmarker = null;
  }

  setPaused(paused: boolean): void {
    if (this.paused === paused) return;
    this.paused = paused;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: paused ? "pause" : "resume" }));
    }
  }

  setTargetFps(fps: number): void {
    this.targetFps = Math.max(1, Math.min(15, fps));
  }

  /** Last N landmark frames (newest last) — used by the pre-flight liveness check. */
  takeRecentLandmarkFrames(n = 6): LandmarkGroups[] {
    return this.landmarkHistory.slice(-n).map((g) => JSON.parse(JSON.stringify(g)) as LandmarkGroups);
  }

  get hasFaceModel(): boolean {
    return this.landmarker !== null;
  }

  // ------------------------------------------------------------------ internals

  private openSocket(sessionId: string): void {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/api/v1/monitoring/session/${sessionId}?mode=browser`);
    ws.onopen = () => {
      // Healthy connection: reset the backoff so a later drop retries fast.
      if (this.ws === ws) this.wsBackoffMs = 1000;
      if (this.paused && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "pause" }));
      }
    };
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === "telemetry_update") {
          this.recentRemote.push(msg);
          if (this.recentRemote.length > 30) this.recentRemote.shift();
          this.opts.onTelemetry?.(this.lastLocalFrame ?? { detected: false, brightness: 0, confidence: 0 }, msg);
        }
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // superseded by a newer socket
      this.ws = null;
      // A dropped socket previously killed monitoring for the whole session
      // (HUD stuck on OFFLINE until restart). Reconnect with capped
      // exponential backoff while the pipeline is still running.
      if (!this.running) return;
      const delay = this.wsBackoffMs;
      this.wsBackoffMs = Math.min(this.wsBackoffMs * 2, 15000);
      this.wsReconnectTimer = setTimeout(() => {
        this.wsReconnectTimer = null;
        if (this.running && !this.ws) this.openSocket(sessionId);
      }, delay);
    };
    this.ws = ws;
  }

  private lastLocalFrame: TelemetryFrame = { detected: false, brightness: 0, confidence: 0 };

  private loop = (): void => {
    if (!this.running) return;
    this.rafId = requestAnimationFrame(this.loop);
    if (this.paused) return;
    const video = this.opts.video;
    if (!video || video.readyState < 2 || !this.landmarker) return;

    const minInterval = 1000 / this.targetFps;
    const now = performance.now();
    if (now - this.lastTick < minInterval) return;
    this.lastTick = now;

    let frame: TelemetryFrame = { detected: false, brightness: 0.5, confidence: 0 };
    try {
      const result = this.landmarker.detectForVideo(video, now);
      const faces = result?.faceLandmarks ?? [];
      const brightness = this.computeBrightness(video);

      if (faces.length > 0) {
        const groups = buildLandmarkGroups(faces[0]);
        this.landmarkHistory.push(groups);
        if (this.landmarkHistory.length > 40) this.landmarkHistory.shift();
        // Anti-spoof texture cue for the backend liveness scorer. Computed
        // every 3rd face frame (~2 Hz at the default 5 FPS target) — cheap
        // at 64×48 but pointless to repeat every tick.
        let textureVar: number | undefined;
        this.tickCount += 1;
        if (this.tickCount % 3 === 1) {
          textureVar = this.computeTextureVariance(video);
        }
        frame = {
          detected: true,
          confidence: 0.95,
          brightness,
          bbox: this.computeBBox(groups.all_points),
          landmarks: groups,
          jpeg_b64: this.snapshotJpeg(video),
          texture_laplacian_var: textureVar,
          timestamp: Date.now() / 1000,
        };
      } else {
        // No face detected — still grab a snapshot so absent-student evidence
        // frames flow to the parent live view and the encrypted evidence ring.
        frame = {
          detected: false,
          confidence: 0.0,
          brightness,
          jpeg_b64: this.snapshotJpeg(video),
          timestamp: Date.now() / 1000,
        };
      }
    } catch (err) {
      console.warn("[vision] tick failed", err);
      return;
    }

    this.lastLocalFrame = frame;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "telemetry", data: frame }));
    }
    if (!this.opts.sessionId) {
      // Local-only mode (pre-flight): surface frames directly.
      this.opts.onTelemetry?.(frame);
    }
  };

  private computeBrightness(video: HTMLVideoElement): number {
    const c = (this.grayCanvas ??= document.createElement("canvas"));
    c.width = 64;
    c.height = 48;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    if (!ctx) return 0.5;
    ctx.drawImage(video, 0, 0, 64, 48);
    const data = ctx.getImageData(0, 0, 64, 48).data;
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) {
      sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    }
    return Math.min(1, sum / (data.length / 4) / 255);
  }

  /** Laplacian variance on a downscaled grayscale copy (anti-spoof texture cue). */
  computeTextureVariance(video: HTMLVideoElement): number {
    const c = (this.grayCanvas ??= document.createElement("canvas"));
    c.width = 64;
    c.height = 48;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    if (!ctx) return 0;
    ctx.drawImage(video, 0, 0, 64, 48);
    const d = ctx.getImageData(0, 0, 64, 48).data;
    const w = 64;
    const h = 48;
    const gray = new Float32Array(w * h);
    for (let i = 0, p = 0; i < d.length; i += 4, p++) {
      gray[p] = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    }
    let sum = 0;
    let sq = 0;
    let n = 0;
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const i = y * w + x;
        const lap =
          4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - w] - gray[i + w];
        sum += lap;
        sq += lap * lap;
        n++;
      }
    }
    if (!n) return 0;
    const mean = sum / n;
    return sq / n - mean * mean;
  }

  private computeBBox(points: LandmarkPoint[]): [number, number, number, number] {
    let minX = 1;
    let minY = 1;
    let maxX = 0;
    let maxY = 0;
    for (const p of points) {
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.x > maxX) maxX = p.x;
      if (p.y > maxY) maxY = p.y;
    }
    return [Math.max(0, minX), Math.max(0, minY), Math.min(1, maxX - minX), Math.min(1, maxY - minY)];
  }

  private snapshotJpeg(video: HTMLVideoElement): string | undefined {
    try {
      const c = (this.snapCanvas ??= document.createElement("canvas"));
      const width = 320;
      const height = Math.round((video.videoHeight || 240) * (width / (video.videoWidth || 320)));
      c.width = width;
      c.height = height || 240;
      const ctx = c.getContext("2d");
      if (!ctx) return undefined;
      ctx.drawImage(video, 0, 0, c.width, c.height);
      return c.toDataURL("image/jpeg", this.opts.jpegQuality ?? 0.6).split(",")[1];
    } catch {
      return undefined;
    }
  }
}
