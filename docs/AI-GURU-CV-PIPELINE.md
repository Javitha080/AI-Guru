# AI Guru — Complete CV Pipeline (Student Monitor)

> What the study-monitoring computer vision actually is, end to end.
> Covers every model, algorithm, threshold, and data path. Internal identifiers
> stay `deeptutor`; user-visible copy says "AI Guru".

## 0. One-sentence truth

There is **no custom trained model**. The pipeline is **2 pretrained MediaPipe
models** + classical CV math (solvePnP, EAR, Laplacian, cosine similarity) +
heuristic state machines. 100% on-device, zero cloud egress for frames.

### Pretrained models (the only AI models in the loop)

| Model | File | Used in |
|---|---|---|
| MediaPipe FaceLandmarker (478 3D landmarks incl. iris, `numFaces=1`) | `web/public/mediapipe/face_landmarker.task` | Backend `deeptutor/services/monitoring/python_face_processor.py` (`RUNNING_MODE VIDEO`) and frontend `web/lib/monitoring/visionPipeline.ts` (`RUNNING_MODE VIDEO`, WASM) |
| EfficientDet-Lite0 COCO detector (only `cell phone` label used) | `web/public/mediapipe/efficientdet_lite0.tflite` | Backend `python_face_processor.py` (`RUNNING_MODE IMAGE`, `score_threshold=0.45`, `max_results=5`, every 5th frame) |
| WASM runtime | `web/public/mediapipe/wasm/` (CDN fallback: jsdelivr + Google storage) | Frontend `FilesetResolver.forVisionTasks()` |

- `opencv-contrib-python>=4.10,<7.0` (`requirements/monitoring.txt`) is a
  library, not a model: capture, color convert, resize, Laplacian, JPEG
  encode, `solvePnP`, overlay drawing.
- No LLM participates in the CV scoring path. LLMs only write the
  post-session report text from already-computed metrics.

## 1. Two engine paths, one scoring core

```
SYSTEM (preferred): SystemCameraManager (OpenCV thread)
  -> PythonFaceProcessor.process_frame() -> FaceFrameResult
  -> SystemMonitorSession._tick(): _build_payload()
  -> LocalCVPipeline.process_telemetry_payload()
  -> broadcast telemetry_update + MJPEG /feed/{id}

BROWSER (fallback): visionPipeline.ts (WASM FaceLandmarker)
  -> WS /session/{id}?mode=browser
  -> browser_driven_monitoring_loop() -> same LocalCVPipeline
  -> same dispatch (telemetry + Telegram outbox + vault)
```

Decision (`deeptutor/api/routers/monitoring_session.py`): if `mode!=browser`
and `camera_config.enabled` and `start_system_monitor()` succeeds → system,
else browser. Frontend probes once via `useMonitorMode` → `GET
/camera/status` (`mode: system|browser`).

Per-session isolation: every WS/system session owns a **fresh
`LocalCVPipeline()`** — presence timers, liveness history, warning cooldowns
never leak across sessions. Only the enrolled identity baseline is copied once
from the global at session start.

## 2. Frontend `visionPipeline.ts` (browser path)

- `start()`: HEAD-probe vendored model, fallback to CDN; GPU delegate, catch →
  CPU; `runningMode: VIDEO`, `numFaces: 1`; open WS via `WsReconnect` when
  `sessionId` is set; `requestAnimationFrame` loop.
- Per tick (throttled to `targetFps`, default 5, clamped 1–15): skip when
  paused, `video.readyState<2`, no landmarker, or interval not elapsed.
- Landmark groups with indices identical to the backend:
  `LEFT_EYE [33,133,159,145,158,153]`,
  `RIGHT_EYE [263,362,386,374,385,380]`,
  `MOUTH [61,291,13,14,82,87]`, `NOSE 1`, `CHIN 152`, `FOREHEAD 10`,
  `L_CHEEK 234`, `R_CHEEK 454`. Missing points default to `(0.5,0.5,0)`.
- Brightness: 64×48 canvas, `g=0.299R+0.587G+0.114B`,
  `brightness=min(1,mean/255)`.
- Texture: Laplacian `4c-top-bottom-left-right` variance, computed **every 3rd
  face frame only**.
- BBox: min/max over `all_points`, clamped 0–1.
- Snapshot: 320px JPEG `q0.6`, only when streaming with socket OPEN. No-face
  frames still snapshot for evidence.
- Frame shape: `{detected, confidence 0.95|0, brightness, bbox?, landmarks?,
  jpeg_b64?, texture_laplacian_var?, timestamp}` sent as
  `{type:telemetry,data:frame}`. Remote `telemetry_update` kept in
  `recentRemote[30]`. Preflight (no sessionId): local frames only.
- `telemetrySocket.ts` (system mode): receives `telemetry_update`, ping every
  25s. `wsReconnect.ts`: capped backoff 1s→15s.

## 3. `SystemCameraManager` (system capture)

Background daemon at `GRAB_TARGET_FPS=15`, default 640×480. Open order
`CAP_MSMF → CAP_DSHOW → CAP_ANY`, hints `MJPG, BUFFERSIZE 1, FPS 15`
best-effort. Cold start gives up after 10s with no frames; warm stream gives
up after 30 consecutive failures. Lazy JPEG caches (raw q80, annotated q80)
re-encoded only when newer than the frame. Registry
`get/release_system_camera(i)` is process-wide per index.

## 4. `PythonFaceProcessor` (system inference)

Lazy-loads both MediaPipe models once. Per frame: brightness from gray mean;
texture Laplacian on 64×48 every 3rd tick; `detect_for_video()` with strictly
increasing `perf_counter` ms; no faces → clear neutral samples, return empty.
Maps the same 478 indices into backend `FaceLandmarks`; EAR via
`face_solvers.compute_ear`; pose via `solve_pnp_angles` + neutral calibration;
gaze via iris offsets; phone detector every 5th tick with 1.5s sticky TTL
(missing model → phone alerts inactive, logged).

Neutral calibration: accumulate frontal samples (`|yaw|<20,|pitch|<25,
|roll|<15`); after 12, median becomes zero-point; later angles are reported
relative to it. Cleared per session.

## 5. `LocalCVPipeline` — the 8 stages

Guards: non-dict payload → not-detected; bad timestamps → `time.time()`; FPS
EMA `0.9*old+0.1*instant`.

1. **Face** (`face_engine.extract_landmarks_from_telemetry`, fail-closed):
   safe floats, validated 4×0–1 bbox, skipped non-dict points, embedding kept
   only if finite list len≥2, geometric fallback never throws.
2. **Identity**: cosine `dot/(|A||B|)` clamped −1..1, `match = sim>=0.65`.
   Face claimed + no usable embedding + baseline enrolled → `False/0.0`
   (spoof bypass closed); un-enrolled mode still passes. `enroll_face()`
   rejects empty, L2-normalizes. Geometric 128D embedding: anchor pairwise
   dist/scale + angle/π, repeated with `1+0.05*sin(i)` to 128D, normalized.
3. **Liveness**: EAR `(v1+v2)/(2h)` per eye (default 0.3 if <6 pts);
   478-mesh `ear_override` preferred. Blink FSM (`closed=ear<0.18`, rising edge
   counts). Texture `<30→v/30 floor 0.2`, `>800→penalized floor 0.3`, else 1.
   Warmup <5 frames → live 0.85. Spoof if no blink + `ear_var<0.0003` +
   `motion<0.00005` → not-live 0.92. Else
   `0.70+0.20·blink+0.05·earDyn+0.05·motion`, ×texture, cap 0.99.
4. **Pose/gaze**: client dicts if both present (fail-closed defaults:
   not-facing/not-reading/not-focused, bad posture → UNKNOWN), else heuristic
   estimator (yaw `asin×1.3`, pitch `asin×1.5`, roll from eye slope) or system
   `solvePnP` (6-pt model, `focal=w`, zero distortion, pitch sign −1; failure
   is `(0,0,0)` neutral). `classify()`: reading `18≤pitch≤55,|yaw|≤25`;
   facing `|yaw|≤25,−15≤pitch<18`; else SLOUCHING/UP/LEFT/RIGHT/TILT/CENTER.
   System gaze `0.75·pose+1.5·iris`, focused if `|gx|≤0.55,gy≤0.62`.
5. **Presence**: `PRESENT → TEMPORARILY_NOT_VISIBLE (5s) → AWAY (20s)`,
   `UNKNOWN` when dark (`lum<20`) and undetected, instant recovery on
   re-detect with `conf≥0.5`.
6. **Distraction**: whitelist first — reading/writing, drink ≤6s, page ≤4s,
   posture-shift ≤4s → `NONE 95–100`. Then `AWAY→STUDENT_AWAY 0/0.98`
   (growing duration), phone `>4s→20/0.92` (pending before),
   mismatch `>15s→10/0.95`, drowsy `ear∈(0,0.18) >4s→15/0.90` (pending
   before), looking-away `|yaw|>35 or pitch<−20, >10s` (pending before).
   Continuous focus `100·yawTerm·pitchTerm·gazeFactor` with neutral bands
   yaw 12° / pitch 10° and `gazeFactor≥0.35`, else focused default.
7. **Engagement**: AWAY 0, TEMP 60, UNKNOWN 50; else gaze 45% + posture 35%
   (CENTER/DOWN 1, TILT 0.85, SLOUCH 0.60, LEFT/RIGHT 0.40) + stability 20%
   (frame deltas `<2.5→1, <8→decay floor 0.5, else 0.3`); −40 if distracted.
   Dual EMA α 0.25 drop / 0.10 recover / 0.15 else; trend RISING/FALLING on
   ±3 over last 10.
8. **Warning** (`evaluate()` = observe+dispatch): confidence ≥0.80, 60s
   per-category cooldown, 5-per-600s rate limit, one-per-episode gate.
   Severities: LOOKING_AWAY warning, PHONE alert, AWAY info, MISMATCH alert,
   DROWSINESS warning. Nudge tier `[3s,6s)` for LOOK/DROWSY/PHONE (incl.
   pending), 40s cooldown, local-only, skipped once escalated.

Strictness profiles: gentle `(90s,0.85)`, balanced `(60s,0.80)`, strict
`(30s,0.75)`, applied from parent settings to both engine paths.

## 6. Helpers and config

- `schemas.py`: `canonical_brightness()`, `parse_pose_gaze()`,
  `TelemetryUpdate` WS shape.
- `landmarks_codec`: canonical landmark dict. `synthetic.py`: synthetic
  landmarks + 8 mock scenarios (normal/absent/writing/drinking/looking/
  phone/static/mismatch). `session_scores.py`: running means + edge-triggered
  episode counts. `face_solvers.py`: stateless EAR/solvePnP/gaze.
- `monitoring_config.DEFAULT_THRESHOLDS` is the single source of truth:
  presence 5/20/20 · distraction 10/4/15/4 · whitelist 6/4/4 · geometry
  45/35/12/10/0.35 + away 35/up −20 · pose 25/18/55 · liveness
  0.18/0.25/0.0003/0.00005/30/800 · warnings 60/0.80/5/600 + nudge 40/3/6 ·
  ring 30/0.5s · client-ts window lag 300s/ahead 5s · outbox 8 retries,
  backoff 30·2ⁿ cap 600s, stale 3600s.
- `ResourceGovernor.get_recommended_cv_fps(10)`: ≥95% CPU/RAM →1,
  ≥85/90 →half (min 2), ≥70% CPU →75% (min 4), else base.

## 7. Loops, dispatch, API, UI

- **System loop** (`SystemMonitorSession`): tick at
  `min(target_fps,governor)` → inference in executor → throttled ring snapshot
  (q70 b64, 30 frames) → pipeline → scores/episodes → `TelemetryUpdate`
  (+ear, warning) → parallel broadcast (1s per-consumer timeout) →
  `spawn_bg(handle_warning)` with ring+photo → persist means every 10s.
  Pause releases the camera; stop cancels, persists, offloads `camera.stop()`.
- **Browser loop**: `session_init{browser}`, honors client timestamps inside
  the acceptance window, same scoring/persist/dispatch over WS.
- **Dispatch** (`dispatch` + `warning_sinks`): persist
  (`NUDGE→info`); nudges stop (local only); warnings/alerts → Telegram outbox
  (photo only on `alert`, downscaled to 960px q70 within 550k chars else
  text-only with a warning log; fan-out per linked parent, drop when
  unconfigured) + vault staging (warning/alert, last 30 ring frames, clip +
  snapshot at 5fps; empty/undecodable rings are logged loudly, never throw).
  Outbox: atomic claim with UUID token, orphan recovery, 8 retries, session
  summaries carry real report metrics + persisted XP.
- **Routers** (`/api/v1/monitoring`, auth-gated, WS auth before accept):
  enroll-face (embedding ≥16D or landmarks), verify-liveness (≥3 frames),
  analyze-frame, status (governor metrics), camera status/config (index 0–8,
  1–30fps), snapshot JPEG, MJPEG feed (12fps), enroll-from-camera,
  camera/probe, live consent/frame, sanitized session events.
- **Frontend**: `study-room/page.tsx` (idle→creating→pre-flight→active→
  completed); `useStudyTelemetry` runs system XOR browser; `PreFlightCheck`
  probes system 24×500ms else browser getUserMedia + 6-frame liveness, amber
  soft-pass never fake-green; `ActiveSessionHUD` shows presence/posture/
  whitelist/focus/engagement/trend + 3-tier warnings + parent live-view toggle.

## 8. What this job deliberately does not do

No custom model training, no cloud video egress, no photo on
warning/nudge (alerts only), no blocking the study loop on a broken sink, no
shared pipeline state across sessions.
