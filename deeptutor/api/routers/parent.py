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
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    status,
)
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


async def parent_context(
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias="dt_token"),
) -> None:
    """Install the per-user workspace context for parent-portal routes.

    Replaces the old router-level ``require_auth`` mount gate. That gate broke
    the documented remote flow: whenever AUTH_ENABLED=true it 401'd the
    bootstrap trio (has-pin / set-pin / verify-pin / refresh) before a remote
    parent — who by definition holds no student JWT — could even check whether
    a PIN exists.

    Behaviour:
    - valid student/user JWT (cookie or bearer) -> that user's workspace;
    - no token, or AUTH_ENABLED=false           -> local admin workspace.

    The parent portal is anchored to the admin workspace by design (pairing,
    PIN and audit data live there), so the fallback is the intended location,
    and every sensitive route *additionally* demands the parent PIN-JWT via
    ``require_parent``.
    """
    from deeptutor.api.routers.auth import (
        _extract_token,
        _install_current_user,
        decode_token,
    )
    from deeptutor.services.auth import AUTH_ENABLED

    payload = None
    if AUTH_ENABLED:
        token = _extract_token(authorization, dt_token)
        if token:
            payload = decode_token(token) or None
    _install_current_user(payload)


def _audit(
    action: str,
    actor: str = "local",
    details: Optional[Dict[str, Any]] = None,
    resource_id: str = "",
    resource_type: str = "parent_portal",
    ip: str = "",
) -> None:
    """Fire-and-forget audit logging; never raises into the request path."""

    async def _run() -> None:
        try:
            await AuditLogger.log_event(
                actor, "parent", action, resource_type, resource_id, details or {}, ip
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("audit log skipped for %s: %s", action, exc)

    from deeptutor.services.background import spawn_bg

    spawn_bg(_run(), name=f"parent-audit-{action}")


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
    port: Optional[int] = Field(
        default=None,
        description="Local target port. Defaults to the FRONTEND port so the "
        "public URL serves the portal UI (which proxies /api to the backend).",
    )


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
        # The PIN epoch bump invalidates every outstanding token by design;
        # tell the client to re-lock explicitly instead of failing the next
        # call with a bare parent_auth_required.
        return {"success": True, "message": "Parent passcode updated.", "reauth_required": True}

    try:
        await JWTAuthService.set_parent_pin(req.pin, parent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _audit("pin.set_initial", actor=parent_id)
    return {"success": True, "message": "Parent passcode successfully saved."}


@router.post("/auth/change-pin")
async def change_parent_pin(
    req: ChangePinRequest, _parent: Dict[str, Any] = Depends(require_parent)
):
    """Change the parent passcode (requires current PIN)."""
    try:
        await JWTAuthService.change_parent_pin(req.pin, req.current_pin, req.parent_id or "default")
    except ValueError as e:
        _audit("pin.change_failed", actor=req.parent_id or "default", details={"reason": str(e)})
        raise HTTPException(status_code=403, detail=str(e))
    _audit("pin.changed", actor=req.parent_id or "default")
    return {"success": True, "message": "Parent passcode updated.", "reauth_required": True}


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
        _audit(
            "pin.verify_failed" if not locked else "pin.lockout",
            actor=req.parent_id or "default",
            details={"reason": str(e)},
            ip=ip,
        )
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/auth/refresh")
async def refresh_parent_token(req: RefreshTokenRequest):
    """Rotate a refresh token: returns a NEW access+refresh pair (old is revoked)."""
    try:
        result = await JWTAuthService.rotate_refresh_token(req.refresh_token)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid_refresh_token")
    return result


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


@router.post("/auth/logout")
async def logout_parent(
    request: Request,
    req: Optional[LogoutRequest] = None,
    _parent: Dict[str, Any] = Depends(require_parent),
):
    """Revoke the presented parent access token and (when supplied) refresh token."""
    token = getattr(request.state, "parent_token", None)
    payload = getattr(request.state, "parent_payload", {}) or {}
    if token and payload.get("jti"):
        await JWTAuthService.revoke_token(payload["jti"])
    if req and req.refresh_token:
        await JWTAuthService.revoke_refresh_token(req.refresh_token)
    _audit("auth.logout", actor=payload.get("sub", "default"))
    return {"success": True}


# ------------------------------- 2. Telegram Bot Configuration & Dispatch


@router.get("/telegram/config", dependencies=[Depends(require_parent)])
async def get_telegram_config(parent_id: str = "default"):
    """Fetch masked Telegram configuration."""
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    try:
        return await TelegramConfigStore.get_masked(parent_id)
    except Exception as exc:  # noqa: BLE001 - unconfigured is a normal state
        logger.debug("Telegram config load failed for %s: %s", parent_id, exc)
    return {"configured": False, "bot_token_masked": "", "chat_id": "", "enabled": False}


@router.post("/telegram/config", dependencies=[Depends(require_parent)])
async def save_telegram_config(req: TelegramConfigRequest):
    """Save Telegram bot credentials.

    A blank ``bot_token`` means "keep the saved one" — the settings UI sends
    an empty field when the parent only wants to update the Chat ID, and
    blindly overwriting would silently disable alert delivery.
    """
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    try:
        await TelegramConfigStore.save(
            req.parent_id or "default",
            bot_token=req.bot_token,
            chat_id=req.chat_id,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _audit("telegram.config_saved", actor=req.parent_id or "default")
    try:
        from deeptutor.services.background import spawn_bg
        from deeptutor.services.monitoring.notification_queue import (
            flush_once,
            start_notification_worker,
        )
        from deeptutor.services.remote.telegram_command_listener import (
            start_telegram_command_listener,
        )

        start_notification_worker()
        start_telegram_command_listener()
        spawn_bg(flush_once(limit=5), name="tg-config-saved-flush")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Background worker activation skipped on config save: %s", exc)

    return {"success": True, "message": "Telegram notifications configured."}


@router.post("/telegram/test", dependencies=[Depends(require_parent)])
async def test_telegram_notification(parent_id: str = "default"):
    """Send a test notification to verify Telegram setup."""
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    config = await TelegramConfigStore.get(parent_id)
    if not config:
        raise HTTPException(status_code=400, detail="Telegram not configured.")

    success, err_detail = await TelegramNotifier.send_message_detailed(
        bot_token=config["bot_token"],
        chat_id=config["chat_id"],
        text=(
            "🎉 <b>AI Guru — Telegram Notifications Connected!</b>\n\n"
            "You will now receive study session start links, real-time distraction alerts, "
            "and end-of-session report cards directly in this chat."
        ),
    )
    _audit("telegram.test_sent", actor=parent_id, details={"success": success})
    if not success:
        raise HTTPException(
            status_code=502,
            detail=err_detail or "Failed to deliver message via Telegram. Check Token and Chat ID.",
        )
    return {"success": True, "message": "Test notification sent successfully."}


def _lan_ip() -> str:
    """Best-effort primary LAN IPv4 (delegates to portal_urls)."""
    from deeptutor.services.remote.portal_urls import lan_ip

    return lan_ip()


def _portal_base_url() -> tuple[str, str]:
    """(base_url, mode) for the parent portal link (delegates to portal_urls)."""
    from deeptutor.services.remote.portal_urls import portal_base_url

    return portal_base_url()


@router.post("/telegram/send-link", dependencies=[Depends(require_parent)])
async def send_tunnel_link_to_telegram(parent_id: str = "default", student_name: str = "Student"):
    """Manually dispatch current parent portal link to Telegram.

    Honest errors: 400 when Telegram is not configured, 502 when the Bot
    API rejects delivery (same contract as /telegram/test).
    """
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    portal_url, mode = _portal_base_url()

    config = await TelegramConfigStore.get(parent_id)
    if not config:
        raise HTTPException(status_code=400, detail="Telegram not configured.")

    access_line = (
        "Reachable via your encrypted outbound tunnel."
        if mode == "tunnel"
        else "Reachable on your home Wi-Fi network only (tunnel not active)."
    )
    success, err_detail = await TelegramNotifier.send_message_detailed(
        bot_token=config["bot_token"],
        chat_id=config["chat_id"],
        text=(
            f"\U0001f517 <b>AI Guru \u2014 Parent Live Portal Link</b>\n\n"
            f"\U0001f464 <b>Student:</b> {student_name}\n"
            f'\U0001f310 <b>Portal URL:</b> <a href="{portal_url}/parent">{portal_url}/parent</a>\n\n'
            f"<i>{access_line} Access is protected by your Parent Passcode PIN.</i>"
        ),
    )
    _audit(
        "telegram.link_sent",
        actor=parent_id,
        details={"success": success, "mode": mode, "error": err_detail or ""},
    )
    if not success:
        raise HTTPException(
            status_code=502,
            detail=err_detail or "Failed to deliver message via Telegram. Check Token and Chat ID.",
        )
    return {"success": True, "url": f"{portal_url}/parent", "mode": mode}


# ------------------------------- 3. Outbound Encrypted Tunnel Endpoints


@router.get("/tunnel/status", dependencies=[Depends(require_parent)])
async def get_tunnel_status():
    """Honest tunnel status incl. whether the URL is publicly reachable."""
    return TunnelGateway.status_snapshot()


@router.post("/tunnel/start")
async def start_tunnel(
    req: StartTunnelRequest = StartTunnelRequest(),  # noqa: B008
    _parent: Dict[str, Any] = Depends(require_parent),
):
    """Start the selected tunnel gateway (Cloudflare or Ngrok)."""
    result = await TunnelGateway.start_tunnel(
        local_port=req.port,
        provider=req.provider,
        ngrok_token=req.ngrok_token,
    )
    _audit(
        "tunnel.start",
        actor=str(_parent.get("sub", "default")),
        details={
            "provider": req.provider,
            "status": result.get("status"),
            "public": result.get("url_is_public"),
        },
    )
    return result


@router.post("/tunnel/stop")
async def stop_tunnel(_parent: Dict[str, Any] = Depends(require_parent)):
    """Stop active tunnel process."""
    await TunnelGateway.stop_tunnel()
    _audit("tunnel.stop", actor=str(_parent.get("sub", "default")))
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


@router.post("/vault/seal")
async def seal_pending_vault(
    req: SealVaultRequest,
    _parent: Dict[str, Any] = Depends(require_parent),
):
    """Encrypt all pending monitoring captures under the parent PIN."""
    try:
        sealed = await VideoVaultManager.seal_pending(req.pin)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    _audit("vault.sealed", actor=str(_parent.get("sub", "default")), details={"count": sealed})
    return {"success": True, "sealed": sealed}


@router.post("/vault/decrypt")
async def decrypt_vault_snapshot(
    req: DecryptVaultRequest,
    _parent: Dict[str, Any] = Depends(require_parent),
):
    """Decrypt a snapshot/clip using Parent PIN (403 on wrong PIN)."""
    parent_id = str(_parent.get("sub", "default"))
    try:
        result = await VideoVaultManager.decrypt_snapshot(
            clip_id=req.clip_id,
            parent_pin=req.pin,
        )
    except PermissionError:
        _audit("vault.decrypt_denied", actor=parent_id, details={"clip_id": req.clip_id})
        raise HTTPException(status_code=403, detail="Invalid Parent PIN.")
    if not result:
        raise HTTPException(status_code=404, detail="Vault item not found or corrupted.")
    _audit("vault.decrypted", actor=parent_id, details={"clip_id": req.clip_id})
    return result


# ------------------------------- 4b. Live Supervision Snapshots --------------


async def _require_live_permission(parent_id: str, session_id: str) -> None:
    """Enforce pairing ``can_view_live`` for explicit links (raises 403).

    No links → the parent passcode gate alone suffices (single-home setup).
    Links exist → the session's student must be linked to this parent AND
    granted live view. Session→student attribution comes from the
    study-session record; when attribution itself fails we fail open (the
    passcode was already verified) and audit the gap instead of breaking
    live view on a study-manager hiccup.
    """
    try:
        links = await PairingService.get_linked_students(parent_id)
    except Exception as exc:  # noqa: BLE001 - permission check must never break frames
        logger.debug("Live permission lookup skipped: %s", exc)
        return
    if not links:
        return
    student_id = ""
    try:
        from deeptutor.services.study.session_manager import StudySessionManager

        sess = await StudySessionManager().get_session(session_id)
        student_id = str((sess or {}).get("student_id") or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Live session attribution skipped for %s: %s", session_id, exc)
    if not student_id:
        _audit("live.unattributed_session", actor=parent_id, details={"session_id": session_id})
        return
    for link in links:
        if str(link.get("student_id")) == student_id:
            perms = link.get("permissions", {}) or {}
            if not perms.get("can_view_live", True):
                _audit(
                    "live.denied_no_permission", actor=parent_id, details={"session_id": session_id}
                )
                raise HTTPException(status_code=403, detail="can_view_live not granted")
            return
    _audit(
        "live.denied_not_linked",
        actor=parent_id,
        details={"session_id": session_id, "student_id": student_id},
    )
    raise HTTPException(status_code=403, detail="student_not_linked_to_parent")


async def _resolve_live_session(
    session_id: Optional[str],
    student_id: Optional[str] = None,
) -> Optional[str]:
    """Map (session_id, student_id) to a concrete monitoring session id.

    An explicit student_id wins: the student's in-progress study session
    (which shares its id with the monitoring socket). Otherwise
    "current"/empty means the first consented-active session. Returns None
    when nothing matches — callers turn that into 404.
    """
    if student_id:
        try:
            from deeptutor.services.study.session_manager import StudySessionManager

            rows = _coerce_session_rows(
                await StudySessionManager().list_sessions(student_id, limit=10)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Live student-session lookup failed for %s: %s", student_id, exc)
            rows = []
        in_prog = next((s for s in rows if s.get("status") == "in_progress"), None)
        if in_prog and in_prog.get("id"):
            return str(in_prog.get("id"))
        return None
    if not session_id or session_id == "current":
        from deeptutor.services.monitoring.session_registry import list_consented_active

        candidates = list_consented_active()
        return candidates[0] if candidates else None
    return session_id


@router.get("/live/status", dependencies=[Depends(require_parent)])
async def live_status(session_id: str = "current") -> Dict[str, Any]:
    """Whether the student's live view is currently consented + streaming."""
    try:
        from deeptutor.services.monitoring.session_registry import (
            has_consent,
            is_session_active,
            list_consented_active,
        )

        if session_id == "current":
            # Any single session with consent+socket counts as live.
            active = list_consented_active()
            return {"available": bool(active), "session_id": active[0] if active else None}
        return {
            "available": has_consent(session_id) and is_session_active(session_id),
            "session_id": session_id,
        }
    except Exception:  # noqa: BLE001
        return {"available": False, "session_id": None}


@router.get("/live/snapshot")
async def live_snapshot(
    _parent: Dict[str, Any] = Depends(require_parent),
    session_id: Optional[str] = None,
    student_id: Optional[str] = None,
):
    """
    Latest consented student frame (JPEG bytes) for the parent portal.

    Permission model: standard parent passcode PLUS, when an explicit
    pairing link exists, ``can_view_live`` for the session's student. The
    pairing check runs BEFORE any frame bytes are touched, for both the
    system-camera and browser-upload frame sources.

    Targeting: explicit ``student_id`` resolves to that student's
    in-progress session; otherwise ``session_id`` (or "current" = first
    consented-active session).
    """
    from fastapi import Response

    try:
        from deeptutor.services.monitoring.session_registry import (
            get_live_frame,
            has_consent,
            is_session_active,
            purge_stale_frames,
        )
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Live supervision unavailable")

    purge_stale_frames()

    session_id = await _resolve_live_session(session_id, student_id)

    if not session_id or not has_consent(session_id) or not is_session_active(session_id):
        raise HTTPException(status_code=404, detail="No live frame available")

    # Pairing permission check FIRST — before either frame source is read.
    await _require_live_permission(str(_parent.get("sub", "default")), session_id)

    # System-camera sessions have no student-side uploads — serve the engine's
    # raw frame directly while consent is on.
    try:
        from deeptutor.services.monitoring.system_monitor import get_system_monitor

        sys_monitor = get_system_monitor(session_id)
    except Exception:  # noqa: BLE001
        sys_monitor = None

    if sys_monitor is not None:
        jpeg = sys_monitor.get_snapshot_jpeg()
        if jpeg is not None:
            _audit(
                "live.snapshot_accessed",
                details={"session_id": session_id, "source": "system_camera"},
            )
            from fastapi import Response as _Response

            return _Response(
                content=jpeg,
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store", "X-Frame-Timestamp": str(time.time())},
            )

    frame = get_live_frame(session_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="No live frame available")

    jpeg_b64, ts = frame
    _audit("live.snapshot_accessed", details={"session_id": session_id})
    import base64 as _b64

    return Response(
        content=_b64.b64decode(jpeg_b64),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Frame-Timestamp": str(ts)},
    )


@router.post("/live/start")
async def parent_start_live_stream(
    _parent: Dict[str, Any] = Depends(require_parent),
    session_id: str = "current",
    student_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Parent-initiated live stream — forces consent without student toggle.

    Also auto-starts the tunnel if not already active, and returns both
    tunnel and LAN URLs so the parent can share or bookmark them.

    Targeting: explicit ``student_id`` resolves to that student's
    in-progress session (403 when the student is not linked to this
    parent); otherwise ``session_id`` ("current" = first active session).
    Pairing ``can_view_live`` is enforced before consent is forced.
    """
    from deeptutor.services.monitoring.session_registry import (
        grant_consent,
        is_session_active,
        list_active_sessions,
    )

    parent_id = str(_parent.get("sub", "default"))
    if student_id:
        resolved = await _resolve_live_session(session_id, student_id)
        if not resolved:
            raise HTTPException(404, "No active study session for this student")
        session_id = resolved
    elif session_id == "current":
        active = list_active_sessions()
        if not active:
            raise HTTPException(404, "No active study session")
        session_id = active[0]

    if not is_session_active(session_id):
        raise HTTPException(404, "Session not found or not active")

    # Pairing gate before forcing consent.
    await _require_live_permission(parent_id, session_id)

    # Force-enable live consent (parent authority)
    grant_consent(session_id)

    # Auto-start tunnel with failure isolation & timeout
    tunnel_url = None
    try:
        if TunnelGateway.is_url_public():
            tunnel_url = TunnelGateway.get_tunnel_url()
        else:
            result = await asyncio.wait_for(TunnelGateway.start_tunnel(), timeout=8.0)
            if result.get("url_is_public"):
                tunnel_url = result.get("url")
    except asyncio.TimeoutError:
        logger.info("Tunnel auto-start taking longer than 8s; continuing with LAN endpoint")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tunnel auto-start in parent_start_live_stream failed: %s", exc)

    # LAN URL with fallback (shared portal_urls helper).
    from deeptutor.services.remote.portal_urls import lan_dashboard_url

    lan_url = lan_dashboard_url() or "http://127.0.0.1:3782/parent"
    tunnel_portal = f"{tunnel_url}/parent" if tunnel_url else None

    _audit(
        "live.parent_initiated_start",
        actor=parent_id,
        details={
            "session_id": session_id,
            "tunnel_url": tunnel_url or "",
        },
    )
    return {
        "session_id": session_id,
        "enabled": True,
        "tunnel_url": tunnel_portal,
        "lan_url": lan_url,
    }


@router.post("/live/stop", dependencies=[Depends(require_parent)])
async def parent_stop_live_stream(
    session_id: str = "current",
) -> Dict[str, Any]:
    """Parent stops live stream and clears in-memory frames."""
    try:
        from deeptutor.services.monitoring.session_registry import clear_all_live, revoke_consent

        if session_id == "current":
            clear_all_live()
            _audit("live.parent_initiated_stop", details={"session_id": "all"})
            return {"stopped": True}

        revoke_consent(session_id)
        _audit("live.parent_initiated_stop", details={"session_id": session_id})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error stopping live stream for %s: %s", session_id, exc)
    return {"session_id": session_id, "stopped": True}


@router.websocket("/live/stream")
async def parent_live_ws_stream(
    ws: WebSocket,
    session_id: str = "current",
    student_id: Optional[str] = None,
):
    """High-speed WebSocket live video stream for the parent dashboard.

    Pushes JPEG frames as binary messages at up to ~5 fps while the
    session is active and consent is on.  Falls back gracefully when
    no frames are available (sends a JSON keep-alive ping every 2s).

    Auth: parent access token via ``Sec-WebSocket-Protocol: parent.<jwt>``
    (preferred — keeps tokens out of URLs and proxy logs), falling back to
    the ``?token=`` query param and the ``aiguru_parent_access`` cookie for
    older clients. Refresh tokens are rejected.
    """
    import base64 as _b64

    from starlette.websockets import WebSocketDisconnect

    # Authenticate the parent: subprotocol first, query/cookie fallback.
    token = ""
    try:
        offered = ws.headers.get("sec-websocket-protocol", "")
        for proto in [p.strip() for p in offered.split(",")]:
            if proto.startswith("parent."):
                token = proto[len("parent.") :]
                break
    except Exception:  # noqa: BLE001 - header parsing must never break auth
        token = ""
    if not token:
        token = ws.query_params.get("token", "")
    if not token:
        token = ws.cookies.get("aiguru_parent_access", "")
    try:
        _parent = await JWTAuthService.verify_parent_access_token(token)
    except Exception as exc:
        logger.debug("Parent live stream WS auth rejected: %s", exc)
        try:
            await ws.close(code=4001, reason="Unauthorized")
        except Exception:
            pass
        return

    try:
        await ws.accept()
    except Exception:
        return

    try:
        from deeptutor.services.monitoring.session_registry import (
            get_live_frame,
            grant_consent,
            is_session_active,
        )
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "message": f"Monitoring unavailable: {exc}"})
            await ws.close()
        except Exception:
            pass
        return

    # Resolve session: explicit student wins, else current/first consented.
    resolved_session = await _resolve_live_session(session_id, student_id)

    if not resolved_session:
        try:
            await ws.send_json({"type": "error", "message": "No active live session"})
            await ws.close()
        except Exception:
            pass
        return
    session_id = resolved_session

    # Pairing gate before forcing consent (403-style close, distinct code).
    try:
        await _require_live_permission(str(_parent.get("sub", "default")), session_id)
    except HTTPException as exc:
        try:
            await ws.send_json({"type": "error", "message": str(exc.detail)})
            await ws.close(code=4003, reason=str(exc.detail)[:120])
        except Exception:
            pass
        return

    # Force consent on (parent-initiated)
    grant_consent(session_id)

    last_ts = 0.0
    try:
        while True:
            # Check session still active
            if not is_session_active(session_id):
                try:
                    await ws.send_json({"type": "ended", "message": "Study session ended"})
                except Exception:
                    pass
                break

            # Try system camera direct frame first
            jpeg_bytes = None
            try:
                from deeptutor.services.monitoring.system_monitor import get_system_monitor

                sys_mon = get_system_monitor(session_id)
                if sys_mon is not None:
                    jpeg_bytes = sys_mon.get_snapshot_jpeg()
            except Exception:
                pass

            if jpeg_bytes is not None:
                await ws.send_bytes(jpeg_bytes)
                last_ts = time.time()
            else:
                live_frame = get_live_frame(session_id)
                if live_frame is not None:
                    frame_b64, ts = live_frame
                    if ts > last_ts:
                        try:
                            await ws.send_bytes(_b64.b64decode(frame_b64))
                            last_ts = ts
                        except Exception:
                            pass
                        continue
                await ws.send_json(
                    {"type": "keepalive" if live_frame else "waiting", "ts": time.time()}
                )

            await asyncio.sleep(0.2)

    except WebSocketDisconnect:
        logger.debug("Parent live stream WS disconnected normally")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    except Exception as exc:
        logger.debug("Parent live stream WS ended: %s", exc)
    finally:
        try:
            await ws.close()
        except Exception:
            pass


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
    payload = json.dumps(
        {
            "student_name": req.student_name.strip() or "Student",
            "daily_goal_minutes": int(req.daily_goal_minutes),
            "alert_strictness": req.alert_strictness,
            "updated_at": time.time(),
        }
    )
    async with aiosqlite.connect(db_path) as db:
        await ensure_kv_settings(db)
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'supervision', ?)",
            (f"supervision_rules_{req.parent_id or 'default'}", payload, time.time()),
        )
        await db.commit()
    _audit(
        "rules.updated",
        actor=req.parent_id or "default",
        details={"strictness": req.alert_strictness},
    )
    return {"success": True, **json.loads(payload)}


# ------------------------------- 5c. Student Pairing & Supervision


@router.post("/pair/generate", dependencies=[Depends(require_parent)])
async def generate_pairing_code(req: GeneratePairingRequest):
    result = await PairingService.generate_pairing_code(req.student_id, req.parent_id)
    _audit(
        "pair.generated",
        actor=req.parent_id,
        details={"student_id": req.student_id},
        resource_type="pairing_link",
        resource_id=result.get("code", ""),
    )
    return result


@router.post("/pair/verify", dependencies=[Depends(require_parent)])
async def verify_pairing_code(req: VerifyPairingRequest):
    link = await PairingService.verify_pairing_code(req.parent_id, req.code)
    if not link:
        _audit("pair.verify_failed", actor=req.parent_id, details={"code_prefix": req.code[:5]})
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    _audit(
        "pair.verified",
        actor=req.parent_id,
        resource_type="pairing_link",
        resource_id=str(link.get("id")),
    )
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


def _local_midnight() -> float:
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _coerce_session_rows(result: Any) -> List[Dict[str, Any]]:
    """Normalize StudySessionManager.list_sessions output.

    The manager historically returned ``List[dict]``; concurrent work may
    switch it to a paginated payload ``{"items": [...], "total": n, ...}``.
    Accept both so the portal never renders fabricated zeros from a shape
    mismatch.
    """
    if isinstance(result, dict):
        items = result.get("items")
        if isinstance(items, list):
            return [row for row in items if isinstance(row, dict)]
        return []
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []


def _today_seconds(rows: List[Dict[str, Any]]) -> float:
    """Sum of study seconds for sessions started today (live in-progress counts up)."""
    midnight = _local_midnight()
    now = time.time()
    total = 0.0
    for s in rows or []:
        started = float(s.get("start_time") or s.get("created_at") or 0)
        if started < midnight:
            continue
        duration = float(s.get("actual_duration_seconds") or 0)
        if s.get("status") == "in_progress":
            duration = max(duration, now - started)
        total += max(0.0, duration)
    return total


def _latest_focus_score(rows: List[Dict[str, Any]]) -> Optional[float]:
    """Most recent COMPLETED session's stored focus score; None when never measured."""
    for s in rows or []:
        if s.get("status") != "completed":
            continue
        raw = s.get("focus_score")
        try:
            value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            value = None
        if value is not None and value > 0:
            return round(value, 1)
    return None


@router.get("/dashboard/{parent_id}", dependencies=[Depends(require_parent)])
async def get_parent_dashboard(parent_id: str):
    students = await PairingService.get_linked_students(parent_id)

    # Live status: a student is 'studying' when they have an open monitoring
    # WebSocket and an in-progress session; otherwise honest 'offline'.
    try:
        from deeptutor.services.monitoring.session_registry import list_active_sessions

        live_sessions = set(list_active_sessions())
    except Exception:  # noqa: BLE001
        live_sessions = set()

    # Fallback display name comes from the persisted supervision rules.
    fallback_name = "Student"
    db_path = _get_db_path()
    try:
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (f"supervision_rules_{parent_id}",)
            )
            row = await cursor.fetchone()
        if row and row[0]:
            rules = json.loads(row[0])
            if str(rules.get("student_name") or "").strip():
                fallback_name = str(rules["student_name"]).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Supervision rules unavailable for dashboard name: %s", exc)

    from deeptutor.services.study.session_manager import StudySessionManager

    manager = StudySessionManager()

    async def _build_row(
        student_id: str, name: str, permissions: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        try:
            rows = _coerce_session_rows(await manager.list_sessions(student_id, limit=30))
        except Exception as exc:  # noqa: BLE001
            logger.debug("activity lookup failed for %s: %s", student_id, exc)

        in_progress = next((s for s in rows if s.get("status") == "in_progress"), None)
        studying = bool(in_progress) and str(in_progress.get("id")) in live_sessions

        gam = {"streak": 0, "xp": 0, "level": 1}
        try:
            from deeptutor.services.gamification.gamification_service import GamificationService

            prof = await GamificationService.get_profile(student_id)
            gam = {
                "streak": prof.get("streak", 0),
                "xp": prof.get("xp", 0),
                "level": prof.get("level", 1),
            }
        except Exception:  # noqa: BLE001
            pass

        row: Dict[str, Any] = {
            "student_id": student_id,
            "name": name,
            "status": "studying" if studying else "offline",
            "current_subject": (in_progress or {}).get("subject") or "",
            "today_study_time": round(_today_seconds(rows) / 60.0, 1),
            "focus_score": _latest_focus_score(rows),
            **gam,
        }
        if permissions is not None:
            row["permissions"] = permissions
        return row

    dashboard_data: List[Dict[str, Any]] = []
    if not students:
        dashboard_data.append(await _build_row("student-primary", fallback_name))
    else:
        # Concurrent per-student lookups (each _build_row is failure-
        # isolated internally, so one bad student never sinks the board).
        dashboard_data = list(
            await asyncio.gather(
                *(
                    _build_row(
                        link.get("student_id", "student"),
                        link.get("student_name") or fallback_name,
                        link.get("permissions", {}),
                    )
                    for link in students
                )
            )
        )

    return dashboard_data


@router.get("/sessions/{student_id}", dependencies=[Depends(require_parent)])
async def get_student_sessions(student_id: str):
    """Real per-student analytics from the local study_sessions table."""
    from deeptutor.services.study.session_manager import StudySessionManager

    manager = StudySessionManager()
    try:
        history = await manager.list_sessions(student_id=student_id, limit=100)
    except TypeError:
        history = await manager.list_sessions(student_id, 100)
    except Exception:
        history = []
    history = _coerce_session_rows(history)

    weekly = [0.0] * 7
    focus_trend: List[float] = []
    session_count_week = 0
    incidents: List[Dict[str, Any]] = []
    now = time.time()
    week_ago = now - 7 * 86400
    month_ago = now - 30 * 86400

    for s in history or []:
        started = float(s.get("start_time") or s.get("created_at") or 0)
        if not started:
            continue
        if started >= week_ago:
            # tm_wday: Monday=0 .. Sunday=6 — matches the Mon..Sun labels.
            day_idx = time.localtime(started).tm_wday
            # In-progress sessions count up live (same rule as the
            # dashboard's today counter); completed ones use stored time.
            duration_s = float(s.get("actual_duration_seconds") or 0)
            if s.get("status") == "in_progress":
                duration_s = max(duration_s, now - started)
            minutes = round(duration_s / 60.0, 1)
            weekly[day_idx] += minutes
            session_count_week += 1
            # Trend only from COMPLETED sessions with a real measurement —
            # live/zero scores would drag the line dishonestly.
            raw_focus = s.get("focus_score")
            try:
                if (
                    raw_focus is not None
                    and s.get("status") == "completed"
                    and float(raw_focus) > 0
                ):
                    focus_trend.append(float(raw_focus))
            except (TypeError, ValueError):
                pass

    session_count_month = sum(
        1
        for s in (history or [])
        if float(s.get("start_time") or s.get("created_at") or 0) >= month_ago
    )

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
                incidents.append(
                    {
                        "time": time.strftime("%H:%M", time.localtime(float(r["timestamp"]))),
                        "timestamp": float(r["timestamp"]),
                        "session_id": r["session_id"],
                        "event": str(meta.get("category") or "Warning").replace("_", " ").title(),
                        "message": str(meta.get("message") or ""),
                        "severity": r["severity"] or "warning",
                        "confidence": float(r["confidence"] or 0),
                        "duration_seconds": float(r["duration_seconds"] or 0),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Incident feed unavailable: %s", exc)

    return {
        "student_id": student_id,
        "weekly_study_time": weekly,
        "focus_trend": focus_trend[-14:],
        "session_count_week": session_count_week,
        "session_count_month": session_count_month,
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
    """Security activity scoped to one parent — never other actors' events.

    Previously an empty result silently widened to *all* portal events,
    leaking other parents' actions into a parent-scoped view and masking
    genuinely empty logs. Empty now honestly means empty.
    """
    return await AuditLogger.get_events(actor_id=parent_id, limit=limit)
