"""Failure-isolated sinks for dispatched monitoring warnings.

Extracted from dispatch.handle_warning so each parent-facing side-effect
(telemetry, Telegram, vault) lives in one testable function. All helpers
swallow their own errors — a broken sink must never crash the monitoring loop.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CAPTURE_SEVERITIES = {"alert", "warning"}
_PHOTO_SEVERITIES = {"alert"}
_PERSISTENCE_SEVERITY = {"nudge": "info"}


def persist_severity(severity: str) -> str:
    return _PERSISTENCE_SEVERITY.get(
        severity, severity if severity in ("info", "warning", "alert") else "warning"
    )


def decode_jpeg(frame_b64: Optional[str]) -> Optional[bytes]:
    if not frame_b64:
        return None
    try:
        return base64.b64decode(frame_b64)
    except Exception:  # noqa: BLE001
        return None


# Telegram sendPhoto cap mirrored in notification_queue._MAX_PHOTO_B64_LEN.
_MAX_PHOTO_B64_LEN = 550_000


def fit_photo_b64(frame_b64: Optional[str]) -> Optional[str]:
    """Downscale an oversized snapshot so the alert keeps its photo.

    Returns a base64 JPEG within the outbox cap, or None when the input is
    absent/undecodable. Without this, any frame over the cap silently
    degraded to a text-only alert with no log line saying why.
    """
    if not frame_b64:
        return None
    if len(frame_b64) <= _MAX_PHOTO_B64_LEN:
        return frame_b64
    raw = decode_jpeg(frame_b64)
    if not raw:
        return None
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(raw)) as img:
            # Header-only dimension check BEFORE touching pixels: Pillow's own
            # decompression-bomb error only fires past ~358MP, but anything
            # above 12MP would already allocate hundreds of MB here for zero
            # evidentiary value (output is a 960px thumbnail anyway).
            if img.size[0] * img.size[1] > 12_000_000:
                logger.warning(
                    "Snapshot dimensions %sx%s exceed 12MP; sending text-only",
                    img.size[0],
                    img.size[1],
                )
                return None
            img = img.convert("RGB")
            img.thumbnail((960, 960), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70, optimize=True)
            shrunk = base64.b64encode(buf.getvalue()).decode("ascii")
        if len(shrunk) > _MAX_PHOTO_B64_LEN:
            logger.warning(
                "Snapshot still %d chars after downscale; sending text-only",
                len(shrunk),
            )
            return None
        logger.info(
            "Downscaled oversized snapshot %d -> %d chars for Telegram photo",
            len(frame_b64),
            len(shrunk),
        )
        return shrunk
    except Exception as exc:  # noqa: BLE001 - photo is best-effort
        logger.warning("Snapshot downscale failed (%s); sending text-only", exc)
        return None


async def persist_warning_event(
    session_id: str,
    warning: Dict[str, Any],
    severity: str,
    confidence: float,
    duration: float,
    is_nudge: bool,
) -> None:
    try:
        from deeptutor.services.study.telemetry_logger import TelemetryLogger

        await TelemetryLogger().log_event(
            session_id=session_id,
            event_type="NUDGE_ISSUED" if is_nudge else "WARNING_ISSUED",
            severity=persist_severity(severity),
            confidence=confidence,
            duration_seconds=duration,
            metadata={
                "category": str(warning.get("category", "NOTICE")),
                "message": warning.get("message", ""),
                "warning_id": warning.get("warning_id", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Warning persistence failed: %s", exc)


async def queue_telegram_notification(
    session_id: str, warning: Dict[str, Any], photo_jpeg_b64: Optional[str] = None
) -> None:
    severity = str(warning.get("severity", "warning"))
    category = str(warning.get("category", "NOTICE"))
    confidence = float(warning.get("confidence", 0.0))
    duration = float(warning.get("duration_seconds", 0.0))

    student_name = "Student"
    student_id = "student-primary"
    subject = "General"
    if session_id:
        try:
            from deeptutor.api.routers.study_session import _resolve_student_name
            from deeptutor.services.study.session_manager import StudySessionManager

            sess = await StudySessionManager().get_session(session_id)
            if sess:
                subject = str(sess.get("subject") or "General")
                student_id = str(sess.get("student_id") or "student-primary")
                student_name = await _resolve_student_name(student_id)
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
        fitted = fit_photo_b64(photo_jpeg_b64)
        if fitted is not None:
            payload["photo_b64"] = fitted
        elif len(photo_jpeg_b64 or "") > _MAX_PHOTO_B64_LEN:
            logger.warning(
                "Dropped oversized Telegram photo for session %s (%d chars); alert sent text-only",
                session_id,
                len(photo_jpeg_b64 or ""),
            )
    try:
        from deeptutor.services.monitoring.notification_queue import (
            enqueue_for_student,
            flush_once,
            start_notification_worker,
        )

        start_notification_worker()
        await enqueue_for_student("warning", payload, student_id)
        try:
            asyncio.get_running_loop().create_task(flush_once(limit=3))
        except RuntimeError:
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Warning notification queueing failed: %s", exc)


async def stage_vault_evidence(
    session_id: str,
    category: str,
    severity: str,
    warning: Dict[str, Any],
    current_frame_b64: Optional[str],
    ring_frames_b64: Optional[List[str]],
) -> None:
    if severity not in _CAPTURE_SEVERITIES:
        return
    try:
        from deeptutor.services.remote.video_vault import VideoVaultManager

        confidence = float(warning.get("confidence", 0.0))
        duration = float(warning.get("duration_seconds", 0.0))
        meta = {
            "confidence": confidence,
            "duration_s": duration,
            "message": warning.get("message", ""),
            "captured_at": time.time(),
        }
        frames = list(ring_frames_b64 or [])
        if not frames and current_frame_b64:
            frames.append(current_frame_b64)
        if not frames:
            # No visual evidence available (empty ring, no current frame):
            # the warning is still persisted + notified, but say so loudly
            # instead of silently staging nothing.
            logger.warning("No vault evidence for %s (%s): frame ring empty", session_id, category)
            return
        if frames:
            decoded_frames = [f for f in (decode_jpeg(x) for x in frames[-30:]) if f]
            if not decoded_frames:
                logger.warning(
                    "No vault evidence for %s (%s): %d ring frame(s) undecodable",
                    session_id,
                    category,
                    len(frames),
                )
                return
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


__all__ = [
    "persist_severity",
    "decode_jpeg",
    "fit_photo_b64",
    "persist_warning_event",
    "queue_telegram_notification",
    "stage_vault_evidence",
]
