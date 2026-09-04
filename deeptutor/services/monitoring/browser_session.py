"""
AI Guru Study Monitoring — Browser-Driven Session Service.
==========================================================

Extracted from the monolithic monitoring.py router. Contains the legacy
browser-driven monitoring loop where the client streams landmark telemetry
(+ optional JPEG snapshots) and the server analyzes on receive.

This module is a pure service — no FastAPI router or endpoint definitions.
It is called by ``monitoring_session.py`` when the system camera is unavailable
and the frontend falls back to browser-side MediaPipe.
"""

from __future__ import annotations

import collections
import json
import logging
import time
from typing import Any, Deque, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from deeptutor.services.monitoring.dispatch import handle_warning
from deeptutor.services.monitoring.monitoring_config import DEFAULT_THRESHOLDS
from deeptutor.services.monitoring.schemas import TelemetryUpdate
from deeptutor.services.monitoring.session_scores import EpisodeTracker, ScoreAccumulator

logger = logging.getLogger(__name__)

# Client-frame timestamp acceptance window (seconds). Within it, the client's
# own observation clock drives the presence/distraction hysteresis; outside
# it the frame falls back to server receive time.
_FRAME_TIMESTAMP_MAX_LAG = DEFAULT_THRESHOLDS.frame_timestamp_max_lag
_FRAME_TIMESTAMP_MAX_AHEAD = DEFAULT_THRESHOLDS.frame_timestamp_max_ahead
_RING_SIZE = DEFAULT_THRESHOLDS.ring_size

_FRAME_KEYS = ("jpeg_b64", "jpeg", "frame_b64", "frame", "image_b64", "image")


def _extract_frame(payload: Dict[str, Any]) -> Optional[str]:
    for key in _FRAME_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and len(value) > 32:
            return value
    return None


async def browser_driven_monitoring_loop(
    websocket: WebSocket,
    session_id: str,
    pipeline: Any,
    frame_rings: Dict[str, Deque[str]],
    active_sessions: Dict[str, WebSocket],
    purge_session_state: Any,
) -> None:
    """
    Legacy browser-driven monitoring loop: the client streams landmark
    telemetry (+ optional JPEG snapshots); the server analyzes on receive.

    Args:
        websocket: The connected WebSocket instance.
        session_id: The monitoring session identifier.
        pipeline: The LocalCVPipeline instance.
        frame_rings: Shared dict of per-session JPEG evidence ring buffers.
        active_sessions: Shared dict of active monitoring WebSocket sessions.
        purge_session_state: Callable to clean up live consent/frames on disconnect.
    """

    logger.info("Monitoring WebSocket connected for session: %s", session_id)

    # --- session-persistence bookkeeping (shared kernel) -----------------------
    # Live scores are periodically flushed into study_sessions and real
    # distraction/presence episodes land in monitoring_events so the report,
    # parent dashboard, and XP flow read actual data instead of zeros.
    # Running means over every analyzed frame. Persisting the LAST frame's
    # instantaneous score instead meant a student who was AWAY when the
    # socket closed got their whole session reported as 0/100 focus.
    score_persist_interval = 10.0
    last_persist = time.time()
    scores = ScoreAccumulator()
    episodes = EpisodeTracker()
    warning_count = 0
    last_presence_state: Optional[str] = None
    is_paused = False

    async def _persist_scores() -> None:
        try:
            from deeptutor.services.study.session_manager import StudySessionManager

            # Use running means only: referencing the last `analysis` frame
            # here caused UnboundLocalError on instant disconnect and biased
            # the whole session toward the final frame's instantaneous score.
            focus = scores.mean_focus(0.0)
            engagement = scores.mean_engagement(0.0)
            await StudySessionManager().update_scores(
                session_id, focus, engagement, episodes.distraction_count, warning_count
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Score persistence skipped for %s: %s", session_id, exc)

    async def _log_episode(
        event_type: str, severity: str, confidence: float, duration_seconds: float, message: str
    ) -> None:
        try:
            from deeptutor.services.study.telemetry_logger import TelemetryLogger

            await TelemetryLogger().log_event(
                session_id=session_id,
                event_type=event_type,
                severity=severity,
                confidence=confidence,
                duration_seconds=duration_seconds,
                metadata={"message": message},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Episode logging skipped for %s/%s: %s", session_id, event_type, exc)

    try:
        # Initial greeting with target FPS
        await websocket.send_json(
            {
                "type": "session_init",
                "session_id": session_id,
                "mode": "browser",
                "target_fps": pipeline.get_current_target_fps(),
                "zero_cloud_egress": True,
                "message": "AI Guru Local Study Monitoring Stream Active",
            }
        )

        while True:
            # Receive telemetry payload from client
            raw_text = await websocket.receive_text()
            try:
                msg = json.loads(raw_text)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type", "telemetry")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
                continue
            elif msg_type == "pause":
                is_paused = True
                continue
            elif msg_type == "resume":
                is_paused = False
                continue

            if is_paused:
                continue

            # A literal ``{"data": null}`` must not poison the pipeline: fall
            # back to the envelope itself so the frame is analyzed, and never
            # hand process_telemetry_payload a None payload.
            data = msg.get("data")
            payload = data if isinstance(data, dict) else msg
            frame_b64 = _extract_frame(payload)
            if frame_b64 is not None:
                ring = frame_rings.setdefault(session_id, collections.deque(maxlen=_RING_SIZE))
                ring.append(frame_b64)

            # Honor the CLIENT observation clock (the frontend stamps every
            # frame). Server receive-time compresses bursted deliveries — GC
            # pauses, network jitter, tab throttling — below the distraction/
            # absence hysteresis thresholds, silently blinding the detector.
            # Bounded acceptance rejects grossly skewed clocks.
            wall_now = time.time()
            frame_ts = payload.get("timestamp")
            if isinstance(frame_ts, (int, float)) and (
                wall_now - _FRAME_TIMESTAMP_MAX_LAG
            ) <= float(frame_ts) <= (wall_now + _FRAME_TIMESTAMP_MAX_AHEAD):
                analysis_ts = float(frame_ts)
            else:
                analysis_ts = wall_now

            analysis = pipeline.process_telemetry_payload(payload, current_time=analysis_ts)

            # Accumulate for the session-mean scores persisted periodically
            # (and once more on disconnect in the finally block).
            scores.add_frame(
                float(analysis.distraction.focus_score or 0),
                float(analysis.engagement.score or 0),
            )

            # --- edge-triggered telemetry persistence (real episodes) -------
            if analysis.presence.state_changed or analysis.presence.state != last_presence_state:
                if (
                    last_presence_state is not None
                    and analysis.presence.state != last_presence_state
                ):
                    await _log_episode(
                        "PRESENCE_CHANGE",
                        "info",
                        float(analysis.gaze.confidence or 0),
                        float(analysis.presence.state_duration_seconds or 0),
                        f"presence -> {analysis.presence.state}",
                    )
                last_presence_state = analysis.presence.state

            dtype = (
                analysis.distraction.distraction_type.value
                if analysis.distraction.is_distracted
                else None
            )
            if episodes.on_frame(analysis.distraction.is_distracted, dtype):
                assert dtype is not None
                event_type = "PHONE_DETECTED" if "PHONE" in dtype.upper() else "LOOKING_AWAY"
                await _log_episode(
                    event_type,
                    "warning",
                    float(analysis.distraction.confidence or 0),
                    float(analysis.distraction.duration_seconds or 0),
                    str(analysis.distraction.reason or dtype),
                )

            if analysis.dispatched_warning:
                # Info-level presence pings (STUDENT_AWAY) and in-app nudges
                # are not actionable warnings; counting them inflated the
                # parent-facing report.
                if analysis.dispatched_warning.severity not in ("info", "nudge"):
                    warning_count += 1

            now_s = time.time()
            if now_s - last_persist >= score_persist_interval:
                last_persist = now_s
                await _persist_scores()

            # Send back real-time metrics (shared TelemetryUpdate shape)
            telemetry_msg = TelemetryUpdate(
                session_id=session_id,
                timestamp=analysis.timestamp,
                presence=analysis.presence.state.value,
                focus_score=analysis.distraction.focus_score,
                engagement_score=analysis.engagement.score,
                engagement_trend=analysis.engagement.trend,
                posture=analysis.pose.posture.value,
                is_distracted=analysis.distraction.is_distracted,
                whitelisted_action=analysis.distraction.whitelisted_action.value
                if analysis.distraction.whitelisted_action
                else None,
                fps=analysis.fps,
            )
            response_data = telemetry_msg.to_dict()

            if analysis.dispatched_warning:
                response_data["warning"] = {
                    "warning_id": analysis.dispatched_warning.warning_id,
                    "category": analysis.dispatched_warning.category,
                    "message": analysis.dispatched_warning.message,
                    "severity": analysis.dispatched_warning.severity,
                }
                warning_dict = {
                    **response_data["warning"],
                    "confidence": analysis.distraction.confidence,
                    "duration_seconds": analysis.distraction.duration_seconds,
                }
                from deeptutor.services.background import spawn_bg

                spawn_bg(
                    handle_warning(
                        session_id=session_id,
                        warning=warning_dict,
                        current_frame_b64=frame_b64,
                        ring_frames_b64=list(frame_rings.get(session_id, ())),
                        photo_jpeg_b64=frame_b64,
                    ),
                    name=f"warning-dispatch-{session_id}",
                )

            await websocket.send_json(response_data)

    except WebSocketDisconnect:
        logger.info("Monitoring WebSocket disconnected for session: %s", session_id)
    except Exception as e:
        logger.warning("Monitoring WebSocket error for session %s: %s", session_id, e)
    finally:
        try:
            await _persist_scores()
        except Exception:  # noqa: BLE001
            pass
        active_sessions.pop(session_id, None)
        frame_rings.pop(session_id, None)
        purge_session_state(session_id)
