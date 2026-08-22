"""
AI Guru Parent Portal & Remote Access API Router.
=================================================

Security model:
- Every route requires a valid **parent** access JWT (issued by verify-pin)
  EXCEPT the bootstrap trio: has-pin / set-pin / verify-pin (+ token refresh).
  The logged-in *student* session does NOT satisfy this gate.
- Changing an existing PIN requires the current PIN (old-PIN confirmation).
- All security-relevant actions are recorded in the local audit log.

Endpoints:
- Parent Passcode PIN authentication & setup ('Ask Pass' Gate)
- Outbound Encrypted Tunnel management (Cloudflare / Ngrok) w/ honest status
- Telegram Bot notification configuration, test, and link dispatch
- Encrypted Local Video Vault: listing, PIN-gated sealing & decryption
- Student pairing links + supervision dashboard data + audit log
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from deeptutor.services.remote.audit_logger import AuditLogger
from deeptutor.services.remote.auth_jwt import JWTAuthService
from deeptutor.services.remote.kv_settings import ensure_kv_settings
from deeptutor.services.remote.pairing import PairingService
from deeptutor.services.remote.telegram_notifier import TelegramNotifier
from deeptutor.services.remote.tunnel_gateway import TunnelGateway
from deeptutor.services.remote.video_vault import VideoVaultManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["parent"])


# ------------------------------------------------------------------ helpers


def _get_db_path():
    from deeptutor.services.path_service import get_path_service
    return get_path_service().user_dir / "chat_history.db"


def _extract_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.cookies.get("dt_parent_token")


async def require_parent(request: Request) -> Dict[str, Any]:
    """FastAPI dependency enforcing the Parent 'Ask Pass' gate server-side."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="parent_auth_required",
        )
    try:
        payload = await JWTAuthService.verify_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="parent_auth_required",
        )
    if payload.get("role") != "parent" or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="parent_auth_required",
        )
    request.state.parent_payload = payload
    request.state.parent_token = token
    return payload


def _audit(action: str, actor: str = "local", details: Optional[Dict[str, Any]] = None,
           resource_id: str = "", resource_type: str = "parent_portal", ip: str = "") -> None:
    """Fire-and-forget audit logging; never raises into the request path."""

    async def _run() -> None:
        try:
            await AuditLogger.log_event(actor, "parent", action, resource_type,
                                        resource_id, details or {}, ip)
        except Exception as exc:  # noqa: BLE001
            logger.debug("audit log skipped for %s: %s", action, exc)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass


# ------------------------------------------------------------------- models


class SetPinRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=8, description="4-8 digit Parent Passcode")
    current_pin: Optional[str] = Field(None, description="Required when changing an existing PIN")
    parent_id: Optional[str] = "default"


class ChangePinRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=8)
    current_pin: str
    parent_id: Optional[str] = "default"


class VerifyPinRequest(BaseModel):
    pin: str = Field(..., description="Parent Passcode PIN")
    parent_id: Optional[str] = "default"
    device_info: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TelegramConfigRequest(BaseModel):
    bot_token: str
    chat_id: str
    enabled: bool = True
    parent_id: Optional[str] = "default"


class StartTunnelRequest(BaseModel):
    provider: str = Field(default="cloudflare", description="'cloudflare' or 'ngrok'")
    ngrok_token: Optional[str] = None
    port: int = 8001


class GeneratePairingRequest(BaseModel):
    student_id: str = "student-primary"
    parent_id: str = "default"


class VerifyPairingRequest(BaseModel):
    parent_id: str = "default"
    code: str


class SealVaultRequest(BaseModel):
    pin: str


class SupervisionRulesRequest(BaseModel):
    student_name: str = Field("Student", max_length=60)
    daily_goal_minutes: int = Field(60, ge=10, le=600)
    alert_strictness: str = Field("balanced", pattern="^(gentle|balanced|strict)$")
    parent_id: Optional[str] = "default"


class DecryptVaultRequest(BaseModel):
    clip_id: str
    pin: str


# ------------------------------------------- 1. Parent Passcode ('Ask Pass')


@router.get("/auth/has-pin")
async def check_has_pin(parent_id: str = "default"):
    """Check if parent PIN passcode is already set up. (Bootstrap â€” ungated.)"""
    has_pin = await JWTAuthService.has_parent_pin(parent_id)
    return {"has_pin": has_pin, "parent_id": parent_id}


@router.post("/auth/set-pin")
async def set_parent_pin(req: SetPinRequest):
    """Set the initial parent passcode; changing an existing one needs current_pin."""
    parent_id = req.parent_id or "default"
    already_set = await JWTAuthService.has_parent_pin(parent_id)
    if already_set:
        if not req.current_pin:
            _audit("pin.change_denied_missing_current", actor=parent_id)
            raise HTTPException(status_code=403, detail="current_pin_required")
        try:
            await JWTAuthService.change_parent_pin(req.pin, req.current_pin, parent_id)
        except ValueError as e:
            _audit("pin.change_failed", actor=parent_id, details={"reason": str(e)})
            raise HTTPException(status_code=403, detail=str(e))
        _audit("pin.changed", actor=parent_id)
        return {"success": True, "message": "Parent passcode updated."}

    try:
        await JWTAuthService.set_parent_pin(req.pin, parent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _audit("pin.set_initial", actor=parent_id)
    return {"success": True, "message": "Parent passcode successfully saved."}


@router.post("/auth/change-pin")
async def change_parent_pin(req: ChangePinRequest,
                            _parent: Dict[str, Any] = Depends(require_parent)):
    """Change the parent passcode (requires current PIN)."""
    try:
        await JWTAuthService.change_parent_pin(req.pin, req.current_pin, req.parent_id or "default")
    except ValueError as e:
        _audit("pin.change_failed", actor=req.parent_id or "default", details={"reason": str(e)})
        raise HTTPException(status_code=403, detail=str(e))
    _audit("pin.changed", actor=req.parent_id or "default")
    return {"success": True, "message": "Parent passcode updated."}


@router.post("/auth/verify-pin")
async def verify_parent_pin(req: VerifyPinRequest, request: Request):
    """Authenticate parent with passcode PIN and issue short-lived JWT pair."""
    ip = request.client.host if request.client else ""
    try:
        result = await JWTAuthService.verify_parent_pin(
            pin=req.pin,
            parent_id=req.parent_id or "default",
            device_info=req.device_info,
        )
        _audit("pin.verify_success", actor=req.parent_id or "default", ip=ip)
        return result
    except ValueError as e:
        locked = "Locked out" in str(e) or "Too many" in str(e)
        _audit("pin.verify_failed" if not locked else "pin.lockout",
               actor=req.parent_id or "default", details={"reason": str(e)}, ip=ip)
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/auth/refresh")
async def refresh_parent_token(req: RefreshTokenRequest):
    """Exchange a refresh token for a fresh 15-min access token."""
    try:
        access_token = await JWTAuthService.refresh_access_token(req.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="invalid_refresh_token")
    return {"access_token": access_token, "token_type": "bearer", "expires_in": 900}


@router.post("/auth/logout")
async def logout_parent(request: Request,
                        _parent: Dict[str, Any] = Depends(require_parent)):
    """Revoke the presented parent access token."""
    token = getattr(request.state, "parent_token", None)
    payload = getattr(request.state, "parent_payload", {}) or {}
    if token and payload.get("jti"):
        await JWTAuthService.revoke_token(payload["jti"])
        _audit("auth.logout", actor=payload.get("sub", "default"))
    return {"success": True}


# ------------------------------- 2. Telegram Bot Configuration & Dispatch


@router.get("/telegram/config", dependencies=[Depends(require_parent)])
async def get_telegram_config(parent_id: str = "default"):
    """Fetch masked Telegram configuration."""
    db_path = _get_db_path()
    try:
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (f"telegram_{parent_id}",))
            row = await cursor.fetchone()
            if row and row[0]:
                data = json.loads(row[0])
                token = data.get("bot_token", "")
                masked_token = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else "****"
                return {
                    "configured": True,
                    "bot_token_masked": masked_token,
                    "chat_id": data.get("chat_id", ""),
                    "enabled": data.get("enabled", True),
                }
    except Exception:
        pass
    return {"configured": False, "bot_token_masked": "", "chat_id": "", "enabled": False}


@router.post("/telegram/config", dependencies=[Depends(require_parent)])
async def save_telegram_config(req: TelegramConfigRequest):
    """Save Telegram bot credentials."""
    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await ensure_kv_settings(db)
        payload = json.dumps({
            "bot_token": req.bot_token,
            "chat_id": req.chat_id,
            "enabled": req.enabled,
            "updated_at": time.time(),
        })
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'telegram', ?)",
            (f"telegram_{req.parent_id or 'default'}", payload, time.time()),
        )
        await db.commit()

    _audit("telegram.config_saved", actor=req.parent_id or "default")
    return {"success": True, "message": "Telegram notifications configured."}


@router.post("/telegram/test", dependencies=[Depends(require_parent)])
async def test_telegram_notification(parent_id: str = "default"):
    """Send a test notification to verify Telegram setup."""
    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (f"telegram_{parent_id}",))
        row = await cursor.fetchone()

    if not row or not row[0]:
        raise HTTPException(status_code=400, detail="Telegram not configured.")

    data = json.loads(row[0])
    success = await TelegramNotifier.send_message(
        bot_token=data.get("bot_token"),
        chat_id=data.get("chat_id"),
        text=(
            "ðŸŽ‰ <b>AI Guru â€” Telegram Notifications Connected!</b>\n\n"
            "You will now receive study session start links, real-time distraction alerts, "
            "and end-of-session report cards directly in this chat."
        ),
    )
    _audit("telegram.test_sent", actor=parent_id, details={"success": success})
    if not success:
        raise HTTPException(status_code=502, detail="Failed to deliver message via Telegram. Check Token and Chat ID.")
    return {"success": True, "message": "Test notification sent successfully."}


@router.post("/telegram/send-link", dependencies=[Depends(require_parent)])
async def send_tunnel_link_to_telegram(parent_id: str = "default", student_name: str = "Student"):
    """Manually dispatch current parent portal link to Telegram."""
    tunnel_url = TunnelGateway.get_tunnel_url() or "http://localhost:3000"

    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (f"telegram_{parent_id}",))
        row = await cursor.fetchone()

    if not row or not row[0]:
        raise HTTPException(status_code=400, detail="Telegram not configured.")

    data = json.loads(row[0])
    success = await TelegramNotifier.send_message(
        bot_token=data.get("bot_token"),
        chat_id=data.get("chat_id"),
        text=(
            f"ðŸ”— <b>AI Guru â€” Parent Live Portal Link</b>\n\n"
            f"ðŸ‘¤ <b>Student:</b> {student_name}\n"
            f"ðŸŒ <b>Portal URL:</b> <a href=\"{tunnel_url}/parent\">{tunnel_url}/parent</a>\n\n"
            f"<i>Access is protected by your Parent Passcode PIN.</i>"
        ),
    )
    _audit("telegram.link_sent", actor=parent_id, details={"success": success})
    return {"success": success, "url": f"{tunnel_url}/parent"}


# ------------------------------- 3. Outbound Encrypted Tunnel Endpoints


@router.get("/tunnel/status", dependencies=[Depends(require_parent)])
async def get_tunnel_status():
    """Honest tunnel status incl. whether the URL is publicly reachable."""
    return TunnelGateway.status_snapshot()


@router.post("/tunnel/start", dependencies=[Depends(require_parent)])
async def start_tunnel(req: StartTunnelRequest = StartTunnelRequest()):
    """Start the selected tunnel gateway (Cloudflare or Ngrok)."""
    result = await TunnelGateway.start_tunnel(
        local_port=req.port,
        provider=req.provider,
        ngrok_token=req.ngrok_token,
    )
    _audit("tunnel.start", actor="default", details={
        "provider": req.provider, "status": result.get("status"),
        "public": result.get("url_is_public"),
    })
    return result


@router.post("/tunnel/stop", dependencies=[Depends(require_parent)])
async def stop_tunnel():
    """Stop active tunnel process."""
    await TunnelGateway.stop_tunnel()
    _audit("tunnel.stop", actor="default")
    return {"status": "inactive"}


# ------------------------------- 4. Encrypted Video & Snapshot Vault


@router.get("/vault/snapshots", dependencies=[Depends(require_parent)])
async def list_vault_snapshots(session_id: Optional[str] = None):
    """List sealed vault items (metadata only) plus pending count."""
    items = await VideoVaultManager.list_encrypted_snapshots(session_id=session_id)
    return {
        "items": items,
        "pending_count": VideoVaultManager.count_pending(),
    }


@router.post("/vault/seal", dependencies=[Depends(require_parent)])
async def seal_pending_vault(req: SealVaultRequest):
    """Encrypt all pending monitoring captures under the parent PIN."""
    try:
        sealed = await VideoVaultManager.seal_pending(req.pin)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    _audit("vault.sealed", details={"count": sealed})
    return {"success": True, "sealed": sealed}


@router.post("/vault/decrypt", dependencies=[Depends(require_parent)])
async def decrypt_vault_snapshot(req: DecryptVaultRequest):
    """Decrypt a snapshot/clip using Parent PIN (403 on wrong PIN)."""
    try:
        result = await VideoVaultManager.decrypt_snapshot(
            clip_id=req.clip_id,
            parent_pin=req.pin,
        )
    except PermissionError:
        _audit("vault.decrypt_denied", details={"clip_id": req.clip_id})
        raise HTTPException(status_code=403, detail="Invalid Parent PIN.")
    if not result:
        raise HTTPException(status_code=404, detail="Vault item not found or corrupted.")
    _audit("vault.decrypted", details={"clip_id": req.clip_id})
    return result


# ------------------------------- 4b. Live Supervision Snapshots --------------


@router.get("/live/status", dependencies=[Depends(require_parent)])
async def live_status(session_id: str = "current") -> Dict[str, Any]:
    """Whether the student's live view is currently consented + streaming."""
    try:
        from deeptutor.api.routers.monitoring import _active_monitoring_sessions, _live_consent

        if session_id == "current":
            # Any single session with consent+socket counts as live.
            active = [sid for sid in _live_consent if sid in _active_monitoring_sessions]
            return {"available": bool(active), "session_id": active[0] if active else None}
        return {
            "available": session_id in _live_consent and session_id in _active_monitoring_sessions,
            "session_id": session_id,
        }
    except Exception:  # noqa: BLE001
        return {"available": False, "session_id": None}


@router.get("/live/snapshot")
async def live_snapshot(
    _parent: Dict[str, Any] = Depends(require_parent),
    session_id: Optional[str] = None,
):
    """
    Latest consented student frame (JPEG bytes) for the parent portal.

    Permission model: parent-controlled switch on the student side PLUS the
    standard parent passcode. When a pairing link exists, ``can_view_live``
    must also be granted.
    """
    from fastapi import Response

    try:
        from deeptutor.api.routers.monitoring import (
            _active_monitoring_sessions,
            _live_consent,
            _live_frames,
            _purge_stale_frames,
        )
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Live supervision unavailable")

    _purge_stale_frames()

    if not session_id or session_id == "current":
        candidates = [sid for sid in _live_consent if sid in _active_monitoring_sessions]
        session_id = candidates[0] if candidates else None

    if (
        not session_id
        or session_id not in _live_consent
        or session_id not in _active_monitoring_sessions
        or session_id not in _live_frames
    ):
        raise HTTPException(status_code=404, detail="No live frame available")

    # Pairing permission check (only when an explicit link exists).
    try:
        links = await PairingService.get_linked_students(str(_parent.get("sub", "default")))
        if links:
            perms = next(
                (link.get("permissions", {}) for link in links if str(link.get("student_id")) == session_id),
                {},
            )
            if perms and not perms.get("can_view_live", True):
                _audit("live.denied_no_permission", actor=str(_parent.get("sub")))
                raise HTTPException(status_code=403, detail="can_view_live not granted")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - permission check must never block frames
        logger.debug("Permission check skipped: %s", exc)

    jpeg_b64, ts = _live_frames[session_id]
    _audit("live.snapshot_accessed", details={"session_id": session_id})
    import base64 as _b64

    return Response(
        content=_b64.b64decode(jpeg_b64),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Frame-Timestamp": str(ts)},
    )


# ------------------------------- 5b. Supervision Rules


@router.get("/supervision-rules", dependencies=[Depends(require_parent)])
async def get_supervision_rules(parent_id: str = "default"):
    """Persisted wizard step-4 rules (student name, daily goal, strictness)."""
    db_path = _get_db_path()
    try:
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (f"supervision_rules_{parent_id}",)
            )
            row = await cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load supervision rules: %s", exc)
    return {"student_name": "Student", "daily_goal_minutes": 60, "alert_strictness": "balanced"}


@router.put("/supervision-rules", dependencies=[Depends(require_parent)])
async def save_supervision_rules(req: SupervisionRulesRequest):
    db_path = _get_db_path()
    payload = json.dumps({
        "student_name": req.student_name.strip() or "Student",
        "daily_goal_minutes": int(req.daily_goal_minutes),
        "alert_strictness": req.alert_strictness,
        "updated_at": time.time(),
    })
    async with aiosqlite.connect(db_path) as db:
        await ensure_kv_settings(db)
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'supervision', ?)",
            (f"supervision_rules_{req.parent_id or 'default'}", payload, time.time()),
        )
        await db.commit()
    _audit("rules.updated", actor=req.parent_id or "default",
           details={"strictness": req.alert_strictness})
    return {"success": True, **json.loads(payload)}


# ------------------------------- 5c. Student Pairing & Supervision


@router.post("/pair/generate", dependencies=[Depends(require_parent)])
async def generate_pairing_code(req: GeneratePairingRequest):
    result = await PairingService.generate_pairing_code(req.student_id, req.parent_id)
    _audit("pair.generated", actor=req.parent_id, details={"student_id": req.student_id},
           resource_type="pairing_link", resource_id=result.get("code", ""))
    return result


@router.post("/pair/verify", dependencies=[Depends(require_parent)])
async def verify_pairing_code(req: VerifyPairingRequest):
    link = await PairingService.verify_pairing_code(req.parent_id, req.code)
    if not link:
        _audit("pair.verify_failed", actor=req.parent_id, details={"code_prefix": req.code[:5]})
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    _audit("pair.verified", actor=req.parent_id, resource_type="pairing_link", resource_id=str(link.get("id")))
    return link


@router.get("/linked-students/{parent_id}", dependencies=[Depends(require_parent)])
async def get_linked_students(parent_id: str):
    return await PairingService.get_linked_students(parent_id)


@router.post("/pair/revoke/{link_id}", dependencies=[Depends(require_parent)])
async def revoke_link(link_id: str):
    ok = await PairingService.revoke_link(link_id)
    _audit("pair.revoked", resource_type="pairing_link", resource_id=link_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"status": "success"}


@router.get("/dashboard/{parent_id}", dependencies=[Depends(require_parent)])
async def get_parent_dashboard(parent_id: str):
    students = await PairingService.get_linked_students(parent_id)

    # Live status: a student is 'studying' when they have an open monitoring
    # WebSocket and an in-progress session; otherwise honest 'offline'.
    try:
        from deeptutor.api.routers.monitoring import _active_monitoring_sessions
        live_sessions = set(_active_monitoring_sessions.keys())
    except Exception:  # noqa: BLE001
        live_sessions = set()

    async def _current_activity(student_id: str) -> Dict[str, Any]:
        try:
            from deeptutor.services.study.session_manager import StudySessionManager

            rows = await StudySessionManager().list_sessions(student_id, limit=5)
            for s in rows or []:
                if s.get("status") == "in_progress":
                    return {
                        "status": "studying" if str(s["id"]) in live_sessions else "offline",
                        "current_subject": s.get("subject") or "",
                        "today_study_time": round((s.get("actual_duration_seconds") or 0) / 60.0, 1),
                    }
        except Exception as exc:  # noqa: BLE001
            logger.debug("activity lookup failed for %s: %s", student_id, exc)
        return {"status": "offline", "current_subject": "", "today_study_time": 0}

    # XP / streak / level come from the real gamification facade.
    async def _gamification(student_id: str) -> Dict[str, Any]:
        try:
            from deeptutor.services.gamification.gamification_service import GamificationService

            prof = await GamificationService.get_profile(student_id)
            return {"streak": prof.get("streak", 0), "xp": prof.get("xp", 0), "level": prof.get("level", 1)}
        except Exception:  # noqa: BLE001
            return {"streak": 0, "xp": 0, "level": 1}

    dashboard_data = []
    if not students:
        student_id = "student-primary"
        activity = await _current_activity(student_id)
        gam = await _gamification(student_id)
        dashboard_data.append({
            "student_id": student_id,
            "name": "Student",
            **activity,
            "focus_score": 0,
            **gam,
        })
    else:
        for link in students:
            student_id = link.get("student_id", "student")
            activity = await _current_activity(student_id)
            gam = await _gamification(student_id)
            dashboard_data.append({
                "student_id": student_id,
                "name": link.get("student_name") or f"Student {str(student_id)[:4]}",
                "permissions": link.get("permissions", {}),
                **activity,
                "focus_score": 0,
                **gam,
            })

    return dashboard_data


@router.get("/sessions/{student_id}", dependencies=[Depends(require_parent)])
async def get_student_sessions(student_id: str):
    """Real per-student analytics from the local study_sessions table."""
    from deeptutor.services.study.session_manager import StudySessionManager

    manager = StudySessionManager()
    try:
        history = await manager.list_sessions(student_id=student_id, limit=50)
    except TypeError:
        history = await manager.list_sessions(student_id)
    except Exception:
        history = []

    weekly = [0.0] * 7
    focus_trend: List[float] = []
    session_count_week = 0
    incidents: List[Dict[str, Any]] = []
    week_ago = time.time() - 7 * 86400

    for s in history or []:
        started = float(s.get("started_at") or s.get("created_at") or 0)
        focus = s.get("focus_score") or 0
        if started >= week_ago:
            day_idx = int((6 - (time.time() - started) // 86400) % 7)
            weekly[day_idx] += round((s.get("duration_seconds") or 0) / 60.0, 1)
            session_count_week += 1
            focus_trend.append(focus)

    # Live incident feed: latest WARNING_ISSUED telemetry across this
    # student's sessions (real data; empty state when none).
    try:
        import aiosqlite as _aiosqlite

        session_ids = [str(s.get("id")) for s in (history or []) if s.get("id")]
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            async with _aiosqlite.connect(_get_db_path()) as db:
                db.row_factory = _aiosqlite.Row
                cursor = await db.execute(
                    f"SELECT session_id, timestamp, severity, confidence, duration_seconds, metadata_json"
                    f" FROM monitoring_events WHERE event_type = 'WARNING_ISSUED' AND session_id IN ({placeholders})"
                    f" ORDER BY timestamp DESC LIMIT 12",
                    session_ids,
                )
                rows = await cursor.fetchall()
            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r["metadata_json"] or "{}")
                except Exception:  # noqa: BLE001
                    pass
                incidents.append({
                    "time": time.strftime("%H:%M", time.localtime(float(r["timestamp"]))),
                    "timestamp": float(r["timestamp"]),
                    "session_id": r["session_id"],
                    "event": str(meta.get("category") or "Warning").replace("_", " ").title(),
                    "message": str(meta.get("message") or ""),
                    "severity": r["severity"] or "warning",
                    "confidence": float(r["confidence"] or 0),
                    "duration_seconds": float(r["duration_seconds"] or 0),
                })
    except Exception as exc:  # noqa: BLE001
        logger.debug("Incident feed unavailable: %s", exc)

    return {
        "student_id": student_id,
        "weekly_study_time": weekly,
        "focus_trend": focus_trend[-14:],
        "session_count_week": session_count_week,
        "session_count_month": len(history or []),
        "recent_incidents": incidents,
        "sessions": history[:10],
    }


@router.get("/reports/{session_id}", dependencies=[Depends(require_parent)])
async def get_session_report(session_id: str):
    """Session report assembled from real stored data when available."""
    from deeptutor.services.study.report_generator import ReportGenerator
    from deeptutor.services.study.telemetry_logger import TelemetryLogger

    generator = ReportGenerator()
    try:
        stored = await generator.get_report(session_id)
    except Exception:
        stored = {}

    if stored:
        return {
            "session_id": session_id,
            "available": True,
            **stored,
        }

    # No generated report yet: fall back to live telemetry summary.
    try:
        events_summary = await TelemetryLogger().get_session_summary(session_id)
    except Exception:
        events_summary = {}
    return {
        "session_id": session_id,
        "available": False,
        "telemetry_summary": events_summary,
        "message": "Report is generated when the study session completes.",
    }


@router.get("/audit-log/{parent_id}", dependencies=[Depends(require_parent)])
async def get_audit_log(parent_id: str, limit: int = Query(20, le=100)):
    events = await AuditLogger.get_events(actor_id=parent_id, limit=limit)
    if not events:
        # Fall back to all parent-portal actions so the log is never mysteriously empty.
        events = await AuditLogger.get_events(limit=limit)
    return events
