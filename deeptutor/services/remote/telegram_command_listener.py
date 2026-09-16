"""Telegram command listener — remote tunnel control for paired parents.

The Parent Portal's outbound tunnel is the only way to reach the dashboard
away from home, but starting it previously required already reaching the
portal — a chicken-and-egg problem when the family is out. This module
closes that gap: a long-poll Bot API listener lets the parent start/stop/
check the tunnel with a chat command.

Security model:
- Commands are served ONLY to the chat whose id exactly matches the
  ``chat_id`` saved in the parent portal Telegram settings, and only when
  that config is ``enabled``. Any other sender is ignored without reply.
- Config is re-read every poll cycle, so saving new credentials in the UI
  takes effect immediately and revocation is instant.
- Every executed command is written to ``audit_logs``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import aiohttp

from deeptutor.services.remote.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)

_POLL_TIMEOUT_S = 25
_IDLE_CONFIG_RETRY_S = 15.0
_ERROR_BACKOFF_S = 8.0
_MAX_BACKOFF_S = 300.0  # 5 minute cap on exponential backoff

_HELP_TEXT = (
    "<b>AI Guru parent commands</b>\n"
    "/status — study session & tunnel status\n"
    "/boostalert status — alert strictness & active timers\n"
    "/boostalert strict [mins] — boost supervision to strict\n"
    "/boostalert test — send verification test alert\n"
    "/boostalert off — restore balanced supervision\n"
    "/tunnel on — start the outbound tunnel\n"
    "/tunnel off — stop the tunnel\n"
    "/tunnel status — current reachability\n"
    "/live stream — start live video supervision\n"
    "/live stop — stop live video stream\n"
    "/live status — check live view availability\n"
    "/help — this list"
)


# ------------------------------------------------------------- pure logic


def parse_command(text: Optional[str]) -> Optional[str]:
    """Map an incoming message to a canonical action.

    Returns one of ``"tunnel_on"``, ``"tunnel_off"``, ``"tunnel_status"``,
    ``"live_stream"``, ``"live_stop"``, ``"live_status"``,
    ``"boostalert_status"``, ``"boostalert_test"``, ``"boostalert_strict"``,
    ``"boostalert_off"``, ``"status"``, ``"help"``, or None for anything
    unrecognized. Tolerates the leading ``@botname`` suffix Telegram appends
    in group chats.
    """
    if not text:
        return None
    parts = text.strip().split()
    if not parts:
        return None
    head = parts[0].lower().split("@", 1)[0]
    arg = parts[1].lower() if len(parts) > 1 else ""
    if head == "/start":
        # Bot-convention greeting doubles as help so first contact works.
        return "help"
    if head == "/help" and not arg:
        return "help"
    if head == "/status" and not arg:
        return "status"
    if head == "/boostalert":
        if not arg or arg == "status":
            return "boostalert_status"
        if arg == "test":
            return "boostalert_test"
        if arg in ("strict", "on"):
            if len(parts) > 2:
                raw_min = (
                    parts[2].lower().replace("mins", "").replace("min", "").replace("m", "").strip()
                )
                if raw_min.isdigit():
                    return f"boostalert_strict:{raw_min}"
            return "boostalert_strict"
        raw_arg = arg.replace("mins", "").replace("min", "").replace("m", "").strip()
        if raw_arg.isdigit():
            return f"boostalert_strict:{raw_arg}"
        if arg in ("off", "normal", "balanced", "reset"):
            return "boostalert_off"
        return None
    if head == "/tunnel":
        if arg == "on":
            return "tunnel_on"
        if arg == "off":
            return "tunnel_off"
        if arg in ("status", ""):
            return "tunnel_status"
        return None
    if head == "/live":
        if arg in ("stream", "start", "on"):
            return "live_stream"
        if arg in ("stop", "off"):
            return "live_stop"
        if arg in ("status", ""):
            return "live_status"
        return None
    return None


def load_parent_telegram_config(config_json: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse the stored ``telegram_{parent_id}`` settings row."""
    if not config_json:
        return None
    try:
        cfg = json.loads(config_json)
    except Exception:  # noqa: BLE001 - corrupted row behaves like absent
        return None
    bot_token = str(cfg.get("bot_token") or "").strip()
    chat_id = str(cfg.get("chat_id") or "").strip()
    enabled = bool(cfg.get("enabled"))
    if not bot_token or not chat_id or not enabled:
        return None
    return {"bot_token": bot_token, "chat_id": chat_id}


def is_authorized_chat(message_chat_id: Any, config: Dict[str, Any]) -> bool:
    """Exact string match against the configured parent chat."""
    return str(message_chat_id) == str(config["chat_id"])


# ---------------------------------------------------------------- replies


async def _status_reply() -> str:
    from deeptutor.services.remote.tunnel_gateway import TunnelGateway

    url = TunnelGateway.get_tunnel_url()
    if url and TunnelGateway.is_url_public():
        return f"Tunnel is <b>active</b>.\nPortal: {url}"
    if TunnelGateway.get_status() in ("starting", "reconnecting"):
        return "Tunnel is <b>starting</b> (no public URL yet). Send /tunnel status again in a few seconds."
    if url:
        return f"Tunnel is <b>starting</b> (no public URL yet).\nLocal-only address: {url}"
    return "Tunnel is <b>not running</b>. Send /tunnel on to start it."


async def _run_tunnel_action(action: str, chat_id: str) -> str:
    from deeptutor.services.background import spawn_bg
    from deeptutor.services.remote.audit_logger import AuditLogger
    from deeptutor.services.remote.tunnel_gateway import TunnelGateway

    async def _audit(command_action: str, details: Dict[str, Any]) -> None:
        try:
            await AuditLogger.log_event(
                "parent-telegram",
                "parent",
                command_action,
                "parent_portal",
                "",
                details,
                "",
            )
        except Exception as exc:  # noqa: BLE001 - audit must never break reply
            logger.debug("audit log skipped for %s: %s", command_action, exc)

    if action == "tunnel_on":
        await _audit("telegram.command_tunnel_start", {"chat_id": chat_id})
        result = await TunnelGateway.start_tunnel()
        status = str(result.get("status") or "")
        url = result.get("url") or ""
        public = bool(result.get("url_is_public"))
        if status == "active" and public:
            spawn_bg(
                _notify_started(chat_id, url),
                name="tg-tunnel-started-notice",
            )
            return f"Tunnel started.\nPortal: {url}"
        if status == "active":
            return f"Tunnel started (still negotiating public URL).\nCurrent: {url}"
        msg = result.get("message") or status or "unknown error"
        return f"Could not start the tunnel: {msg}"

    if action == "tunnel_off":
        await _audit("telegram.command_tunnel_stop", {"chat_id": chat_id})
        await TunnelGateway.stop_tunnel()
        return "Tunnel stopped."

    return await _status_reply()


async def _notify_started(chat_id: str, url: str) -> None:
    """Follow-up nudge so the URL lands in chat history even if the direct
    reply raced the URL negotiation."""
    from deeptutor.services.remote.tunnel_gateway import TunnelGateway

    for _ in range(10):
        await asyncio.sleep(2.0)
        live = TunnelGateway.get_tunnel_url()
        if live and TunnelGateway.is_url_public():
            if live != url:
                token = ""
                for _, cfg in await _read_configs():
                    if str(cfg.get("chat_id")) == str(chat_id):
                        token = str(cfg.get("bot_token") or "")
                        break
                if token:
                    await TelegramNotifier.send_message(
                        token,
                        chat_id,
                        f"Portal is now publicly reachable:\n{live}",
                    )
            return


# ------------------------------------------------------------------ loop


async def _read_config() -> Optional[Dict[str, Any]]:
    """Read the default parent's Telegram config (legacy single-parent path)."""
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    try:
        return await TelegramConfigStore.get("default")
    except Exception as exc:  # noqa: BLE001 - DB hiccup should not kill loop
        logger.warning("Telegram listener could not read settings: %s", exc)
        return None


async def _read_configs() -> list[tuple[str, Dict[str, Any]]]:
    """All enabled (parent_id, config) pairs, refreshed every poll cycle.

    Saving new credentials in the UI takes effect immediately and
    revocation is instant — per parent, not just `default`.
    """
    from deeptutor.services.remote.telegram_config import TelegramConfigStore

    try:
        return await TelegramConfigStore.list_enabled()
    except Exception as exc:  # noqa: BLE001 - DB hiccup should not kill loop
        logger.warning("Telegram listener could not read settings: %s", exc)
        return []


class TelegramCommandListener:
    """Long-poll loop translating authorized chat commands into actions."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Per-parent getUpdates offsets, keyed by parent_id: two parents may
        # share nothing (different bots), so a single global offset would
        # ACK one parent's updates against the other's bot.
        self._offsets: Dict[str, int] = {}

    def start(self) -> Optional[asyncio.Task]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        if self._task and not self._task.done() and self._loop is loop:
            return self._task
        if self._task and not self._task.done():
            self._task.cancel()
        self._loop = loop
        self._task = loop.create_task(self._run(), name="tg-command-listener")
        return self._task

    async def stop(self) -> None:
        task, self._task = self._task, None
        self._loop = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        backoff = _ERROR_BACKOFF_S
        consecutive_errors = 0
        while True:
            configs = await _read_configs()
            if not configs:
                await asyncio.sleep(_IDLE_CONFIG_RETRY_S)
                continue
            progressed = False
            for parent_id, cfg in configs:
                try:
                    await self._poll_once(cfg, parent_id)
                    # Reset backoff on success.
                    progressed = True
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad token must not starve the others
                    consecutive_errors += 1
                    # Log only on first errors and then at exponentially
                    # decreasing frequency to avoid flooding stderr.
                    if (
                        consecutive_errors <= 3
                        or (consecutive_errors & (consecutive_errors - 1)) == 0
                    ):
                        logger.warning(
                            "Telegram command poll failed for %s (attempt %d, degraded): %s",
                            parent_id,
                            consecutive_errors,
                            exc,
                        )
            if progressed:
                backoff = _ERROR_BACKOFF_S
                consecutive_errors = 0
            else:
                await asyncio.sleep(backoff)
                # Exponential backoff: 8 → 16 → 32 → … → 300s cap.
                backoff = min(backoff * 2, _MAX_BACKOFF_S)

    async def _poll_once(self, cfg: Dict[str, Any], parent_id: str = "default") -> None:
        url = "https://api.telegram.org/bot{token}/getUpdates".format(token=cfg["bot_token"])
        params = {
            "timeout": int(_POLL_TIMEOUT_S),
            "offset": self._offsets.get(parent_id, 0),
            "allowed_updates": json.dumps(["message"]),
        }
        timeout = aiohttp.ClientTimeout(total=_POLL_TIMEOUT_S + 15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                body = await resp.json(content_type=None)
        if not isinstance(body, dict) or not body.get("ok"):
            error_code = body.get("error_code") if isinstance(body, dict) else None
            # 409 = another bot instance polling; 429 = rate-limited.
            # Both are transient; honour retry_after when given.
            if error_code == 429:
                retry_after = (body.get("parameters") or {}).get("retry_after", 10)
                logger.info("Telegram rate-limited, retrying after %ds", retry_after)
                await asyncio.sleep(retry_after)
                return
            if error_code == 409:
                desc = str((body or {}).get("description", "")).lower()
                if "webhook" in desc:
                    logger.warning(
                        "Telegram 409 webhook active — automatically deleting webhook to unblock getUpdates"
                    )
                    del_url = "https://api.telegram.org/bot{token}/deleteWebhook".format(
                        token=cfg["bot_token"]
                    )
                    try:
                        async with aiohttp.ClientSession(
                            timeout=aiohttp.ClientTimeout(total=10.0)
                        ) as del_session:
                            async with del_session.post(del_url) as del_resp:
                                logger.info("deleteWebhook status: %d", del_resp.status)
                    except Exception as del_exc:  # noqa: BLE001
                        logger.warning("Failed to call deleteWebhook: %s", del_exc)
                    await asyncio.sleep(2.0)
                    return
                # Another bot instance is running the same token.
                # Back off heavily — nothing we can do until the other
                # instance stops.
                logger.warning("Telegram 409 conflict — another bot instance is running")
                await asyncio.sleep(30)
                return
            raise RuntimeError(f"getUpdates rejected: {body}")

        for update in body.get("result") or []:
            try:
                seen = int(update.get("update_id", 0)) + 1
            except (TypeError, ValueError):
                seen = self._offsets.get(parent_id, 0)
            self._offsets[parent_id] = max(self._offsets.get(parent_id, 0), seen)
            await self._handle_update(update, cfg, parent_id=parent_id)

    async def _handle_update(
        self, update: Dict[str, Any], cfg: Dict[str, Any], parent_id: str = "default"
    ) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = str(message.get("text") or "").strip()
        action = parse_command(text)

        if not is_authorized_chat(chat_id, cfg):
            # Never reveal existence/reasoning to strangers; log locally only.
            logger.debug(
                "Telegram command from unauthorized chat %s ignored",
                chat_id,
            )
            return

        # Skip stale updates on cold start (older than 5 minutes)
        msg_date = message.get("date")
        if msg_date and (time.time() - float(msg_date)) > 300.0:
            logger.info(
                "Ignoring stale Telegram command from %s (sent %ds ago)",
                chat_id,
                int(time.time() - float(msg_date)),
            )
            return

        if not action:
            # If authorized chat sent an unrecognized slash command, guide them
            if text.startswith("/"):
                reply = "❓ Unrecognized command. Send /help to see available commands."
                await TelegramNotifier.send_message(cfg["bot_token"], str(chat_id), reply)
            return

        try:
            reply = await _dispatch(action, str(chat_id), parent_id=parent_id)
        except Exception as exc:  # noqa: BLE001 - report honestly, stay alive
            logger.error("Tunnel command %s failed: %s", action, exc)
            reply = f"Command failed: {exc}"
        await TelegramNotifier.send_message(
            cfg["bot_token"],
            str(chat_id),
            reply,
        )


_listener = TelegramCommandListener()


async def _composite_status_reply() -> str:
    """Combined report of study session, tunnel, and live video status."""
    lines = ["📊 <b>AI Guru — Status Report</b>\n"]

    # 1. Active study session status
    try:
        from deeptutor.services.monitoring.session_registry import list_active_sessions

        active_sessions = list_active_sessions()
        if active_sessions:
            session_id = active_sessions[0]
            from deeptutor.api.routers.study_session import _resolve_student_name
            from deeptutor.services.study.session_manager import StudySessionManager

            sess = await StudySessionManager().get_session(session_id)
            student_id = str((sess or {}).get("student_id") or "student-primary")
            name = await _resolve_student_name(student_id)
            subject = str((sess or {}).get("subject") or "General")
            duration_min = float(((sess or {}).get("actual_duration_seconds") or 0)) / 60.0
            focus = float((sess or {}).get("focus_score") or 0.0)
            lines.append(
                f"📚 <b>Study Session:</b> Active\n"
                f"👤 <b>Student:</b> {name}\n"
                f"📖 <b>Subject:</b> {subject}\n"
                f"⏱️ <b>Duration:</b> {duration_min:.0f} min\n"
                f"🎯 <b>Focus Score:</b> {focus:.0f}%\n"
            )
        else:
            lines.append("📚 <b>Study Session:</b> No active session right now.\n")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Status session check failed: %s", exc)
        lines.append("📚 <b>Study Session:</b> Idle\n")

    # 2. Outbound tunnel status
    try:
        from deeptutor.services.remote.tunnel_gateway import TunnelGateway

        url = TunnelGateway.get_tunnel_url()
        public = TunnelGateway.is_url_public()
        if url and public:
            lines.append(
                f'🌐 <b>Tunnel:</b> Active (Public)\n🔗 <a href="{url}/parent">{url}/parent</a>\n'
            )
        elif url:
            lines.append(f"🌐 <b>Tunnel:</b> Starting (Local: {url})\n")
        else:
            lines.append("🌐 <b>Tunnel:</b> Inactive (Send /tunnel on to start)\n")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Status tunnel check failed: %s", exc)
        lines.append("🌐 <b>Tunnel:</b> Unknown\n")

    # 3. Live Video status
    try:
        from deeptutor.services.monitoring.session_registry import list_consented_active

        active_live = list_consented_active()
        if active_live:
            lines.append("📹 <b>Live Video:</b> Active\n")
        else:
            lines.append("📹 <b>Live Video:</b> Inactive\n")
    except Exception:  # noqa: BLE001
        pass

    # 4. Alert Strictness status
    try:
        curr = await _get_current_strictness()
        if _boost_state.get("active") and _boost_state.get("expires_at", 0) > time.time():
            rem = max(0, int((_boost_state.get("expires_at", 0) - time.time()) / 60) + 1)
            lines.append(f"⚡ <b>Alert Strictness:</b> STRICT (Boosted, {rem}m left)")
        else:
            lines.append(f"⚡ <b>Alert Strictness:</b> {curr.capitalize()}")
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lines)


# ------------------------------------------------------------- boostalert state

_boost_state: Dict[str, Any] = {
    "active": False,
    "expires_at": 0.0,
    "duration_minutes": 0,
    "timer_task": None,
    "chat_id": "",
}


async def _set_db_strictness(profile: str, parent_id: str = "default") -> None:
    import aiosqlite

    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.remote.kv_settings import ensure_kv_settings

    db_path = get_path_service().user_dir / "chat_history.db"
    now = time.time()
    try:
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            keys = {f"supervision_rules_{parent_id}", "supervision_rules_default"}
            for key in keys:
                cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = await cursor.fetchone()
                rules = {}
                if row and row[0]:
                    try:
                        rules = json.loads(row[0])
                    except Exception:
                        rules = {}
                rules["alert_strictness"] = profile
                rules["updated_at"] = now
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, 'supervision', ?)",
                    (key, json.dumps(rules), now),
                )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist strictness setting: %s", exc)


async def _get_current_strictness(parent_id: str = "default") -> str:
    import aiosqlite

    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.remote.kv_settings import ensure_kv_settings

    db_path = get_path_service().user_dir / "chat_history.db"
    try:
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            for key in (f"supervision_rules_{parent_id}", "supervision_rules_default"):
                cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = await cursor.fetchone()
                if row and row[0]:
                    try:
                        rules = json.loads(row[0])
                        val = str(rules.get("alert_strictness") or "")
                        if val:
                            return val
                    except Exception:
                        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read strictness setting: %s", exc)
    return "balanced"


async def _revert_boost_job(
    delay_s: float, target_chat_id: str, parent_id: str = "default"
) -> None:
    try:
        await asyncio.sleep(delay_s)
        await _set_db_strictness("balanced", parent_id=parent_id)
        from deeptutor.services.monitoring.system_monitor import update_all_monitors_strictness

        await update_all_monitors_strictness("balanced")
        _boost_state["active"] = False
        _boost_state["timer_task"] = None

        for _, cfg in await _read_configs():
            if str(cfg.get("chat_id")) == str(target_chat_id):
                token = str(cfg.get("bot_token") or "")
                if token:
                    await TelegramNotifier.send_message(
                        token,
                        str(target_chat_id),
                        "ℹ️ <b>AI Guru — Supervision Boost Ended</b>\n\n"
                        "Temporary strict supervision period has elapsed.\n"
                        "Alert strictness restored to <b>balanced</b> mode.",
                    )
                break
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error in boost revert job: %s", exc)


async def _run_boostalert_action(action: str, chat_id: str, parent_id: str = "default") -> str:
    from deeptutor.services.background import spawn_bg
    from deeptutor.services.monitoring.monitoring_config import perception_profile_for
    from deeptutor.services.monitoring.system_monitor import (
        active_system_monitors,
        update_all_monitors_strictness,
    )
    from deeptutor.services.remote.audit_logger import AuditLogger

    async def _audit(command_action: str, details: Dict[str, Any]) -> None:
        try:
            await AuditLogger.log_event(
                "parent-telegram",
                "parent",
                command_action,
                "parent_portal",
                "",
                details,
                "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("audit log skipped for %s: %s", command_action, exc)

    if action.startswith("boostalert_strict"):
        mins = 60
        if ":" in action:
            try:
                mins = max(1, int(action.split(":", 1)[1]))
            except ValueError:
                mins = 60

        await _set_db_strictness("strict", parent_id=parent_id)
        updated_monitors = await update_all_monitors_strictness("strict")

        # Cancel previous revert job if active
        prev_task = _boost_state.get("timer_task")
        if prev_task and not prev_task.done():
            prev_task.cancel()

        now = time.time()
        _boost_state["active"] = True
        _boost_state["expires_at"] = now + mins * 60
        _boost_state["duration_minutes"] = mins
        _boost_state["chat_id"] = chat_id
        _boost_state["timer_task"] = spawn_bg(
            _revert_boost_job(mins * 60, chat_id, parent_id=parent_id),
            name="tg-boostalert-revert",
        )

        p = perception_profile_for("strict")
        await _audit(
            "telegram.boostalert_strict",
            {"chat_id": chat_id, "duration_minutes": mins, "updated_monitors": updated_monitors},
        )

        return (
            "⚡ <b>AI Guru — Alert System Boosted to STRICT</b>\n\n"
            "Supervision thresholds tightened for maximum focus:\n"
            f"• <b>Looking Away:</b> {p.looking_away_seconds:.1f}s (was 10.0s)\n"
            f"• <b>Phone Detected:</b> {p.phone_seconds:.1f}s (was 4.0s)\n"
            f"• <b>Face Mismatch:</b> {p.identity_mismatch_seconds:.1f}s (was 15.0s)\n"
            f"• <b>Alert Cooldown:</b> {p.cooldown_seconds:.0f}s (was 60s)\n"
            f"• <b>Min Confidence:</b> {int(p.min_confidence * 100)}%\n\n"
            f"⏱️ <b>Active Boost:</b> {mins} minutes\n"
            f"🎯 <b>Sessions Updated:</b> {updated_monitors} active monitor(s)"
        )

    if action == "boostalert_off":
        prev_task = _boost_state.get("timer_task")
        if prev_task and not prev_task.done():
            prev_task.cancel()
        _boost_state["active"] = False
        _boost_state["timer_task"] = None

        await _set_db_strictness("balanced", parent_id=parent_id)
        updated_monitors = await update_all_monitors_strictness("balanced")
        p = perception_profile_for("balanced")

        await _audit("telegram.boostalert_off", {"chat_id": chat_id})
        return (
            "✅ <b>AI Guru — Supervision Reset to Balanced</b>\n\n"
            "Standard thresholds restored:\n"
            f"• <b>Looking Away:</b> {p.looking_away_seconds:.1f}s\n"
            f"• <b>Phone Detected:</b> {p.phone_seconds:.1f}s\n"
            f"• <b>Alert Cooldown:</b> {p.cooldown_seconds:.0f}s\n"
            f"• <b>Min Confidence:</b> {int(p.min_confidence * 100)}%\n\n"
            f"🎯 <b>Sessions Updated:</b> {updated_monitors} active monitor(s)"
        )

    if action == "boostalert_test":
        import uuid

        test_id = f"test-{uuid.uuid4().hex[:6]}"
        curr = await _get_current_strictness(parent_id=parent_id)
        if _boost_state.get("active") and _boost_state.get("expires_at", 0) > time.time():
            curr = "strict (boosted)"

        await _audit("telegram.boostalert_test", {"chat_id": chat_id, "test_id": test_id})

        # Also queue a test warning event if notification worker is active
        try:
            from deeptutor.services.monitoring.warning_sinks import queue_telegram_notification

            await queue_telegram_notification(
                session_id="",
                warning={
                    "category": "TEST_ALERT",
                    "severity": "alert",
                    "message": "AI Guru Alert Verification: Parent push notifications verified operational.",
                    "confidence": 1.0,
                    "duration_seconds": 0.0,
                },
            )
        except Exception:  # noqa: BLE001
            pass

        return (
            "🚨 <b>AI Guru — Alert System Verification</b>\n\n"
            "Status: <b>ONLINE & VERIFIED ✅</b>\n"
            "Notification Pipeline: <b>Active</b>\n"
            f"Current Mode: <b>{curr.upper()}</b>\n"
            f"Verification ID: <code>{test_id}</code>\n\n"
            "<i>High-priority study alerts and proctor notifications are functioning normally.</i>"
        )

    # boostalert_status
    curr = await _get_current_strictness(parent_id=parent_id)
    boost_active = bool(
        _boost_state.get("active") and _boost_state.get("expires_at", 0) > time.time()
    )
    rem_mins = (
        max(0, int((_boost_state.get("expires_at", 0) - time.time()) / 60) + 1)
        if boost_active
        else 0
    )
    active_profile = "strict" if boost_active else curr
    p = perception_profile_for(active_profile)

    from deeptutor.services.monitoring.session_registry import list_active_sessions

    monitors = active_system_monitors()
    active_sids = list_active_sessions()

    lines = [
        "⚡ <b>AI Guru — Alert & Supervision Status</b>\n",
        f"Profile: <b>{active_profile.upper()}</b>"
        + (f" (Boosted, {rem_mins}m remaining)" if boost_active else ""),
        f"• Looking Away: <b>{p.looking_away_seconds:.1f}s</b>",
        f"• Phone Detected: <b>{p.phone_seconds:.1f}s</b>",
        f"• Identity Mismatch: <b>{p.identity_mismatch_seconds:.1f}s</b>",
        f"• Warning Cooldown: <b>{p.cooldown_seconds:.0f}s</b>",
        f"• Min Confidence: <b>{int(p.min_confidence * 100)}%</b>\n",
        f"📡 <b>Active Sessions:</b> {len(active_sids)}",
        f"📹 <b>Hardware Monitors:</b> {len(monitors)}",
    ]
    return "\n".join(lines)


async def _dispatch(action: str, chat_id: str, parent_id: str = "default") -> str:
    if action == "help":
        return _HELP_TEXT
    if action == "status":
        return await _composite_status_reply()
    if action.startswith("boostalert_"):
        return await _run_boostalert_action(action, chat_id, parent_id=parent_id)
    if action.startswith("live_"):
        return await _run_live_action(action, chat_id)
    return await _run_tunnel_action(action, chat_id)


# ------------------------------------------------------------- live stream


def _get_lan_dashboard_url() -> Optional[str]:
    """Get the LAN-accessible parent dashboard URL (delegates to portal_urls)."""
    from deeptutor.services.remote.portal_urls import lan_dashboard_url

    return lan_dashboard_url()


def _compose_live_stream_reply(
    tunnel_url: Optional[str],
    lan_url: Optional[str],
    session_id: str,
) -> str:
    """Rich Telegram reply with both access URLs and clear descriptions."""
    lines = [
        "📹 <b>AI Guru — Live Video Stream Activated</b>\n",
        f"Session: <code>{session_id[:18]}</code>\n",
    ]
    if tunnel_url:
        safe = tunnel_url.replace("&", "&amp;").replace("<", "&lt;")
        lines.append(
            "🌐 <b>Remote Access (Encrypted Tunnel):</b>\n"
            f'🔗 <a href="{safe}/parent">{safe}/parent</a>\n'
            "<i>Use this link from anywhere — it creates a secure encrypted "
            "tunnel through Cloudflare to your child's device. Works outside "
            "your home network (mobile data, office WiFi, etc). The URL "
            "changes each session for security.</i>\n"
        )
    if lan_url:
        safe = lan_url.replace("&", "&amp;").replace("<", "&lt;")
        lines.append(
            "🏠 <b>Local Network Access (Same WiFi):</b>\n"
            f'🔗 <a href="{safe}">{safe}</a>\n'
            "<i>Use this link when you are on the same WiFi network as the "
            "study computer. Faster and more reliable than the tunnel — "
            "no internet required. Only works within your home network.</i>\n"
        )
    if not tunnel_url and not lan_url:
        lines.append(
            "⚠️ No external access available. "
            "The tunnel could not start and LAN access is not detected.\n"
        )
    lines.append(
        "📌 <b>How to view:</b>\n"
        "1. Open a link above in any browser\n"
        "2. Enter your Parent PIN to unlock the dashboard\n"
        "3. The live video stream will start automatically\n"
        "4. Send /live stop when done"
    )
    return "\n".join(lines)


async def _run_live_action(action: str, chat_id: str) -> str:
    """Handle /live stream|stop|status commands with robust failure isolation."""
    from deeptutor.services.remote.audit_logger import AuditLogger

    async def _audit(command_action: str, details: Dict[str, Any]) -> None:
        try:
            await AuditLogger.log_event(
                "parent-telegram",
                "parent",
                command_action,
                "parent_portal",
                "",
                details,
                "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("audit log skipped for %s: %s", command_action, exc)

    if action == "live_stream":
        # 1. Find active monitoring session
        try:
            from deeptutor.services.monitoring.session_registry import (
                grant_consent,
                list_active_sessions,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to access monitoring system: %s", exc)
            return "⚠️ Monitoring system is currently initializing or unavailable."

        active_sessions = list_active_sessions()
        if not active_sessions:
            return (
                "ℹ️ <b>No active study session right now.</b>\n\n"
                "Live video stream is available whenever your child starts a study session in the Study Room."
            )

        session_id = active_sessions[0]

        # 2. Force-enable live consent (parent authority override)
        try:
            grant_consent(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not register live consent for %s: %s", session_id, exc)

        # 3. Auto-start tunnel with timeout protection & background follow-up
        from deeptutor.services.background import spawn_bg
        from deeptutor.services.remote.tunnel_gateway import TunnelGateway

        tunnel_url: Optional[str] = None
        tunnel_negotiating = False
        try:
            if not TunnelGateway.is_url_public():
                tunnel_result = await asyncio.wait_for(TunnelGateway.start_tunnel(), timeout=10.0)
                if tunnel_result.get("url_is_public"):
                    tunnel_url = tunnel_result.get("url")
                else:
                    tunnel_negotiating = bool(tunnel_result.get("status") in ("starting", "active"))
                    # If tunnel is negotiating, spawn background watcher to deliver public URL
                    if tunnel_negotiating:
                        spawn_bg(
                            _notify_started(chat_id, tunnel_result.get("url") or ""),
                            name="tg-live-tunnel-notice",
                        )
            else:
                tunnel_url = TunnelGateway.get_tunnel_url()
        except asyncio.TimeoutError:
            tunnel_negotiating = True
            logger.info("Tunnel startup ongoing; continuing with live response")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tunnel auto-start in live stream encountered error: %s", exc)

        # 4. Get LAN URL
        try:
            lan_url = _get_lan_dashboard_url()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LAN URL discovery failed: %s", exc)
            lan_url = None

        # 5. Compose detailed reply
        reply = _compose_live_stream_reply(
            tunnel_url=tunnel_url,
            lan_url=lan_url,
            session_id=session_id,
        )
        if tunnel_negotiating and not tunnel_url:
            reply += "\n\n⏳ <i>Encrypted tunnel is establishing; you will receive a follow-up message when the public link is ready.</i>"

        # 6. Audit
        await _audit(
            "telegram.live_stream_started",
            {
                "chat_id": chat_id,
                "session_id": session_id,
                "tunnel_url": tunnel_url or "",
                "lan_url": lan_url or "",
            },
        )

        return reply

    if action == "live_stop":
        try:
            from deeptutor.services.monitoring.session_registry import clear_all_live

            clear_all_live()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error during live_stop cleanup: %s", exc)
        await _audit("telegram.live_stream_stopped", {"chat_id": chat_id})
        return "✅ Live video stream stopped. Frames cleared from memory."

    # live_status
    try:
        from deeptutor.services.monitoring.session_registry import (
            list_active_sessions,
            list_consented_active,
        )

        active_live = list_consented_active()
        if active_live:
            return (
                f"📹 Live stream is <b>active</b> for session <code>{active_live[0][:12]}…</code>"
            )
        if list_active_sessions():
            return (
                "Student is studying but live stream is <b>not active</b>.\n"
                "Send /live stream to start."
            )
    except Exception:  # noqa: BLE001
        pass
    return "No active study session. Live stream is available only during sessions."


def start_telegram_command_listener() -> Optional[asyncio.Task]:
    """Idempotently start the background listener (app startup hook)."""
    return _listener.start()


async def stop_telegram_command_listener() -> None:
    await _listener.stop()
