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
from typing import Any, Dict, Optional

import aiohttp

from deeptutor.services.path_service import get_path_service
from deeptutor.services.remote.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)

_POLL_TIMEOUT_S = 25
_IDLE_CONFIG_RETRY_S = 15.0
_ERROR_BACKOFF_S = 8.0

_HELP_TEXT = (
    "<b>AI Guru parent commands</b>\n"
    "/tunnel on — start the outbound tunnel\n"
    "/tunnel off — stop the tunnel\n"
    "/tunnel status — current reachability\n"
    "/help — this list"
)


# ------------------------------------------------------------- pure logic


def parse_command(text: Optional[str]) -> Optional[str]:
    """Map an incoming message to a canonical action.

    Returns one of ``"tunnel_on"``, ``"tunnel_off"``, ``"tunnel_status"``,
    ``"help"``, or None for anything unrecognized. Tolerates the leading
    ``@botname`` suffix Telegram appends in group chats.
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
    if head != "/tunnel":
        return None
    if arg == "on":
        return "tunnel_on"
    if arg == "off":
        return "tunnel_off"
    if arg in ("status", ""):
        return "tunnel_status"
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
    if url:
        return (
            f"Tunnel is <b>starting</b> (no public URL yet).\nLocal-only address: {url}"
        )
    return "Tunnel is <b>not running</b>. Send /tunnel on to start it."


async def _run_tunnel_action(action: str, chat_id: str) -> str:
    from deeptutor.services.background import spawn_bg
    from deeptutor.services.remote.audit_logger import AuditLogger
    from deeptutor.services.remote.tunnel_gateway import TunnelGateway

    async def _audit(command_action: str, details: Dict[str, Any]) -> None:
        try:
            await AuditLogger.log_event(
                "parent-telegram", "parent", command_action,
                "parent_portal", "", details, "",
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
                _notify_started(chat_id, url), name="tg-tunnel-started-notice",
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
                cfg = await _read_config()
                token = cfg["bot_token"] if cfg else ""
                await TelegramNotifier.send_message(
                    token, chat_id,
                    f"Portal is now publicly reachable:\n{live}",
                )
            return


# ------------------------------------------------------------------ loop


async def _read_config() -> Optional[Dict[str, Any]]:
    """Read the default parent's Telegram config straight from SQLite."""
    import aiosqlite

    from deeptutor.services.remote.kv_settings import ensure_kv_settings

    db_path = get_path_service().user_dir / "chat_history.db"
    try:
        async with aiosqlite.connect(db_path) as db:
            await ensure_kv_settings(db)
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", ("telegram_default",),
            )
            row = await cursor.fetchone()
            return load_parent_telegram_config(row[0] if row else None)
    except Exception as exc:  # noqa: BLE001 - DB hiccup should not kill loop
        logger.warning("Telegram listener could not read settings: %s", exc)
        return None


class TelegramCommandListener:
    """Long-poll loop translating authorized chat commands into actions."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._offset: int = 0

    def start(self) -> Optional[asyncio.Task]:
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self._run(), name="tg-command-listener")
        return self._task

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            cfg = await _read_config()
            if not cfg:
                await asyncio.sleep(_IDLE_CONFIG_RETRY_S)
                continue
            try:
                await self._poll_once(cfg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                logger.warning("Telegram command poll failed: %s", exc)
                await asyncio.sleep(_ERROR_BACKOFF_S)

    async def _poll_once(self, cfg: Dict[str, Any]) -> None:
        url = (
            "https://api.telegram.org/bot{token}/getUpdates".format(token=cfg["bot_token"])
        )
        params = {
            "timeout": int(_POLL_TIMEOUT_S),
            "offset": self._offset,
            "allowed_updates": json.dumps(["message"]),
        }
        timeout = aiohttp.ClientTimeout(total=_POLL_TIMEOUT_S + 15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                body = await resp.json(content_type=None)
        if not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError(f"getUpdates rejected: {body}")

        for update in body.get("result") or []:
            self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
            await self._handle_update(update, cfg)

    async def _handle_update(self, update: Dict[str, Any], cfg: Dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        action = parse_command(message.get("text"))

        if not action:
            return
        if not is_authorized_chat(chat_id, cfg):
            # Never reveal existence/reasoning to strangers; log locally only.
            logger.debug(
                "Telegram command from unauthorized chat %s ignored", chat_id,
            )
            return

        try:
            reply = await _dispatch(action, str(chat_id))
        except Exception as exc:  # noqa: BLE001 - report honestly, stay alive
            logger.error("Tunnel command %s failed: %s", action, exc)
            reply = f"Command failed: {exc}"
        await TelegramNotifier.send_message(
            cfg["bot_token"], str(chat_id), reply,
        )


_listener = TelegramCommandListener()


async def _dispatch(action: str, chat_id: str) -> str:
    if action == "help":
        return _HELP_TEXT
    return await _run_tunnel_action(action, chat_id)


def start_telegram_command_listener() -> Optional[asyncio.Task]:
    """Idempotently start the background listener (app startup hook)."""
    return _listener.start()


async def stop_telegram_command_listener() -> None:
    await _listener.stop()
