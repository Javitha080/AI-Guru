"""Glue between the local CV pipeline and parent-facing subsystems.

Connects three previously-dead ends:

1. Dispatched warnings  -> telemetry persistence (TelemetryLogger)
                        -> Telegram outbox (notification_queue)
                        -> encrypted vault staging (VideoVaultManager pending/)
2. Session completion   -> ReportGenerator + Telegram session summary

All functions are failure-isolated: a broken sink must never crash the
study-session monitoring loop.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Severity levels that warrant capturing encrypted evidence into the vault.
_CAPTURE_SEVERITIES = {"alert", "warning"}
# High-priority alerts carry the camera snapshot to Telegram (warnings remain text-only).
_PHOTO_SEVERITIES = {"alert"}
# monitoring_events.severity is CHECK-constrained to info/warning/alert;
# in-app-only nudges persist as informational episodes.
_PERSISTENCE_SEVERITY = {"nudge": "info"}


def _persist_severity(severity: str) -> str:
    return _PERSISTENCE_SEVERITY.get(
        severity, severity if severity in ("info", "warning", "alert") else "warning"
    )


def _decode_jpeg(frame_b64: Optional[str]) -> Optional[bytes]:
    if not frame_b64:
        return None
    try:
        return base64.b64decode(frame_b64)
    except Exception:  # noqa: BLE001
        return None


async def handle_warning(
    session_id: str,
    warning: Dict[str, Any],
    current_frame_b64: Optional[str] = None,
    ring_frames_b64: Optional[List[str]] = None,
    photo_jpeg_b64: Optional[str] = None,
) -> None:
    """Persist + notify + stage evidence for one dispatched warning.

    Tiering policy lives here:
    - ``nudge``  → telemetry only (severity mapped to info), no parent send,
    - ``warning``/``alert`` → telemetry + Telegram + vault staging; ``alert``
      additionally carries the live camera snapshot as a Telegram photo.
    """
    category = str(warning.get("category", "NOTICE"))
    severity = str(warning.get("severity", "warning"))
    confidence = float(warning.get("confidence", 0.0))
    duration = float(warning.get("duration_seconds", 0.0))
    is_nudge = severity == "nudge"

    # 1. Persist to monitoring_events via TelemetryLogger (batched writer).
    try:
        from deeptutor.services.study.telemetry_logger import TelemetryLogger

        await TelemetryLogger().log_event(
            session_id=session_id,
            event_type="NUDGE_ISSUED" if is_nudge else "WARNING_ISSUED",
            severity=_persist_severity(severity),
            confidence=confidence,
            duration_seconds=duration,
            metadata={
                "category": category,
                "message": warning.get("message", ""),
                "warning_id": warning.get("warning_id", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Warning persistence failed: %s", exc)

    # Nudges are student-facing only — never leave the machine.
    if is_nudge:
        return

    # 2. Queue parent Telegram notification (survives offline). Alerts attach
    # the actual incident frame so parents see what happened.
    student_name = "Student"
    subject = "General"
    if session_id:
        try:
            from deeptutor.api.routers.study_session import _resolve_student_name
            from deeptutor.services.study.session_manager import StudySessionManager

            sess = await StudySessionManager().get_session(session_id)
            if sess:
                subject = str(sess.get("subject") or "General")
                s_id = str(sess.get("student_id") or "student-primary")
                student_name = await _resolve_student_name(s_id)
        except Exception:  # noqa: BLE001
            pass

    payload = {
        "session_id": session_id,
        "student_name": student_name,
        "subject": subject,
        "category": category,
        "message": warning.get("message", ""),
        "severity": severity,
        "confidence": confidence,
        "duration_seconds": duration,
        "timestamp": time.time(),
    }
    if severity in _PHOTO_SEVERITIES and photo_jpeg_b64:
        payload["photo_b64"] = photo_jpeg_b64
    try:
        from deeptutor.services.monitoring.notification_queue import (
            enqueue,
            flush_once,
            start_notification_worker,
        )

        start_notification_worker()
        await enqueue("warning", payload)

        # Best-effort immediate delivery; failures stay queued.
        try:
            asyncio.get_running_loop().create_task(flush_once(limit=3))
        except RuntimeError:
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Warning notification queueing failed: %s", exc)

    # 3. Stage encrypted-vault evidence (snapshot + trailing clip).
    if severity in _CAPTURE_SEVERITIES:
        try:
            from deeptutor.services.remote.video_vault import VideoVaultManager

            meta = {
                "confidence": confidence,
                "duration_s": duration,
                "message": warning.get("message", ""),
                "captured_at": time.time(),
            }
            # The WS ring already contains the current frame as its last entry;
            # only append when no ring was supplied.
            frames = list(ring_frames_b64 or [])
            if not frames and current_frame_b64:
                frames.append(current_frame_b64)

            if frames:
                decoded_frames = [f for f in (_decode_jpeg(x) for x in frames[-30:]) if f]
                fps = 5.0
                if len(decoded_frames) >= 2:
                    await VideoVaultManager.save_pending_clip(
                        session_id, category, decoded_frames, fps, dict(meta)
                    )
                await VideoVaultManager.save_pending_snapshot(
                    session_id, category, decoded_frames[-1], dict(meta)
                )
                logger.info("Staged vault evidence for %s (%s)", session_id, category)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Vault evidence capture skipped: %s", exc)


async def handle_session_completed(
    session_id: str,
    student_id: str = "student-primary",
) -> None:
    """Generate the stored report and queue the parent summary notification."""
    duration_minutes = 0.0
    focus_score = 0.0
    engagement_score = 0.0
    warning_count = 0
    summary_text = ""
    xp_earned = 0

    # 1. Generate + persist the AI report (LLM best-effort inside generator).
    try:
        from deeptutor.services.study.report_generator import ReportGenerator

        report = await ReportGenerator().generate_report(session_id, student_id)
        summary_text = str(report.get("ai_tutor_feedback", "") or "")
    except Exception as exc:  # noqa: BLE001
        logger.info("Report generation skipped for %s: %s", session_id, exc)

    # 2. Aggregate metrics from session row + telemetry.
    try:
        from deeptutor.services.study.session_manager import StudySessionManager
        from deeptutor.services.study.telemetry_logger import TelemetryLogger

        session = await StudySessionManager().get_session(session_id)
        if session:
            focus_score = float(session.get("focus_score") or 0)
            engagement_score = float(session.get("engagement_score") or 0)
            warning_count = int(session.get("warning_count") or 0)
            duration_minutes = float(session.get("actual_duration_seconds") or 0) / 60.0
        tel_summary = await TelemetryLogger().get_session_summary(session_id)
        # Count only actionable warnings; info-level presence pings
        # (STUDENT_AWAY) must not inflate the parent-facing report.
        warning_count = max(
            warning_count,
            int(tel_summary.get("actionable_warnings", 0)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Session metrics aggregation failed: %s", exc)

    # 2b. Award real XP for the completed session + evaluate badges.
    try:
        from deeptutor.services.gamification.gamification_service import GamificationService

        focus = focus_score or 0
        xp_earned = int(max(5, min(200, duration_minutes * 2 + focus * 0.8)))
        await GamificationService.award_xp(
            student_id,
            xp_earned,
            f"session_completed:{session_id}",
            session_id=session_id,
        )
        await GamificationService.check_and_award(student_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Session XP award skipped: %s", exc)
        xp_earned = 0

    # Report the XP that is ACTUALLY persisted in rewards (0 when the award
    # failed) — never the formula's intention.
    try:
        from deeptutor.services.study.session_manager import StudySessionManager

        xp_earned = await StudySessionManager()._session_xp(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("XP read-back failed for %s: %s", session_id, exc)

    # 3. Queue the parent-facing summary.
    subject = "General"
    if session:
        subject = str(session.get("subject") or "General")
    student_name = student_id
    try:
        from deeptutor.api.routers.study_session import _resolve_student_name

        student_name = await _resolve_student_name(student_id)
    except Exception:  # noqa: BLE001
        pass

    try:
        from deeptutor.services.monitoring.notification_queue import (
            enqueue,
            start_notification_worker,
        )

        start_notification_worker()
        await enqueue(
            "session_summary",
            {
                "session_id": session_id,
                "student_id": student_id,
                "student_name": student_name,
                "subject": subject,
                "duration_minutes": round(duration_minutes, 1),
                "focus_score": focus_score,
                "engagement_score": engagement_score,
                "warning_count": warning_count,
                "summary": summary_text[:600],
                "xp_earned": xp_earned,
            },
        )

        # Best-effort immediate delivery; failures stay queued.
        try:
            from deeptutor.services.monitoring.notification_queue import flush_once

            asyncio.get_running_loop().create_task(flush_once(limit=3))
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Session summary queueing failed: %s", exc)
