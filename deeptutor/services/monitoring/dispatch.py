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
import logging
from typing import Any, Dict, List, Optional

from deeptutor.services.monitoring.warning_sinks import (
    persist_warning_event,
    queue_telegram_notification,
    stage_vault_evidence,
)

logger = logging.getLogger(__name__)

# Backward-compat re-exports (pre-refactor private helpers).
from deeptutor.services.monitoring import warning_sinks as _warning_sinks  # noqa: F401

_decode_jpeg = _warning_sinks.decode_jpeg
_persist_severity = _warning_sinks.persist_severity

__all__ = ["handle_warning", "handle_session_completed", "_decode_jpeg", "_persist_severity"]

_CAPTURE_SEVERITIES = {"alert", "warning"}
_PHOTO_SEVERITIES = {"alert"}


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

    await persist_warning_event(session_id, warning, severity, confidence, duration, is_nudge)

    # Nudges are student-facing only — never leave the machine.
    if is_nudge:
        return

    await queue_telegram_notification(session_id, warning, photo_jpeg_b64)
    await stage_vault_evidence(
        session_id, category, severity, warning, current_frame_b64, ring_frames_b64
    )


async def handle_session_completed(
    session_id: str,
    student_id: str = "student-primary",
) -> None:
    """Generate the stored report and queue the parent summary notification."""
    summary_text = await _build_session_report(session_id, student_id)
    metrics = await _aggregate_session_metrics(session_id)
    xp_earned = await _award_session_xp(
        session_id, student_id, metrics["duration_minutes"], metrics["focus_score"]
    )
    await _queue_session_summary(session_id, student_id, summary_text, metrics, xp_earned)


async def _build_session_report(session_id: str, student_id: str) -> str:
    try:
        from deeptutor.services.study.report_generator import ReportGenerator

        report = await ReportGenerator().generate_report(session_id, student_id)
        return str(report.get("ai_tutor_feedback", "") or "")
    except Exception as exc:  # noqa: BLE001
        logger.info("Report generation skipped for %s: %s", session_id, exc)
        return ""


async def _aggregate_session_metrics(session_id: str) -> Dict[str, Any]:
    duration_minutes = 0.0
    focus_score = 0.0
    engagement_score = 0.0
    warning_count = 0
    subject = "General"
    try:
        from deeptutor.services.study.session_manager import StudySessionManager
        from deeptutor.services.study.telemetry_logger import TelemetryLogger

        session: Dict[str, Any] = await StudySessionManager().get_session(session_id) or {}
        if session:
            focus_score = float(session.get("focus_score") or 0)
            engagement_score = float(session.get("engagement_score") or 0)
            warning_count = int(session.get("warning_count") or 0)
            duration_minutes = float(session.get("actual_duration_seconds") or 0) / 60.0
            subject = str(session.get("subject") or "General")
        tel_summary = await TelemetryLogger().get_session_summary(session_id)
        warning_count = max(warning_count, int(tel_summary.get("actionable_warnings", 0)))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Session metrics aggregation failed: %s", exc)
    return {
        "duration_minutes": duration_minutes,
        "focus_score": focus_score,
        "engagement_score": engagement_score,
        "warning_count": warning_count,
        "subject": subject,
    }


async def _award_session_xp(
    session_id: str, student_id: str, duration_minutes: float, focus_score: float
) -> int:
    try:
        from deeptutor.services.gamification.gamification_service import GamificationService

        focus = focus_score or 0
        xp_guess = int(max(5, min(200, duration_minutes * 2 + focus * 0.8)))
        await GamificationService.award_xp(
            student_id, xp_guess, f"session_completed:{session_id}", session_id=session_id
        )
        await GamificationService.check_and_award(student_id, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Session XP award skipped: %s", exc)
        return 0
    # Report the XP that is ACTUALLY persisted in rewards (0 when the award
    # failed) — never the formula's intention.
    try:
        from deeptutor.services.study.session_manager import StudySessionManager

        return await StudySessionManager()._session_xp(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("XP read-back failed for %s: %s", session_id, exc)
        return 0


async def _queue_session_summary(
    session_id: str,
    student_id: str,
    summary_text: str,
    metrics: Dict[str, Any],
    xp_earned: int,
) -> None:
    student_name = student_id
    try:
        from deeptutor.api.routers.study_session import _resolve_student_name

        student_name = await _resolve_student_name(student_id)
    except Exception:  # noqa: BLE001
        pass

    try:
        from deeptutor.services.monitoring.notification_queue import (
            enqueue_for_student,
            start_notification_worker,
        )

        start_notification_worker()
        await enqueue_for_student(
            "session_summary",
            {
                "session_id": session_id,
                "student_id": student_id,
                "student_name": student_name,
                "subject": str(metrics.get("subject") or "General"),
                "duration_minutes": round(float(metrics.get("duration_minutes") or 0), 1),
                "focus_score": metrics.get("focus_score") or 0,
                "engagement_score": metrics.get("engagement_score") or 0,
                "warning_count": metrics.get("warning_count") or 0,
                "summary": summary_text[:600],
                "xp_earned": xp_earned,
            },
            student_id,
        )

        # Best-effort immediate delivery; failures stay queued.
        try:
            from deeptutor.services.monitoring.notification_queue import flush_once

            asyncio.get_running_loop().create_task(flush_once(limit=3))
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Session summary queueing failed: %s", exc)
