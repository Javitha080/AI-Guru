"""
AI Guru Outbound Encrypted Tunnel Gateway.
==========================================

Manages zero-configuration encrypted outbound tunnels (Cloudflare Quick Tunnel
or Ngrok) for remote parent supervision across NAT and firewalls.
Never exposes raw database ports or requires manual router port forwarding.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class TunnelGateway:
    """Manages outbound encrypted tunnel processes for parent remote access."""

    _process: Optional[asyncio.subprocess.Process] = None
    _tunnel_url: Optional[str] = None
    _status: str = "inactive"
    _provider: str = "cloudflare"
    _read_task: Optional[asyncio.Task] = None
    _url_is_public: bool = False
    _watchdog_task: Optional[asyncio.Task] = None
    _last_port: int = 8001
    _last_ngrok_token: Optional[str] = None
    _restart_attempts: int = 0

    @classmethod
    async def start_tunnel(
        cls,
        local_port: int = 8001,
        provider: str = "cloudflare",
        ngrok_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start the selected outbound tunnel gateway."""
        if cls._process and cls._status == "active" and cls._tunnel_url:
            return {
                "status": "active",
                "url": cls._tunnel_url,
                "provider": cls._provider,
                "url_is_public": cls._url_is_public,
            }

        cls._last_port = local_port
        cls._last_ngrok_token = ngrok_token or cls._last_ngrok_token
        cls._restart_attempts = 0
        cls._status = "starting"
        cls._provider = provider

        # 1. Cloudflare Quick Tunnel (Recommended, No Account Required)
        if provider == "cloudflare" or (provider == "auto" and shutil.which("cloudflared")):
            if shutil.which("cloudflared"):
                try:
                    cmd = ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{local_port}"]
                    cls._process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    cls._status = "starting"
                    cls._provider = "cloudflare"

                    # Start background stream parser to capture dynamic trycloudflare URL
                    cls._read_task = asyncio.create_task(cls._read_cloudflared_output())

                    # Wait up to 8 seconds for URL discovery
                    for _ in range(16):
                        await asyncio.sleep(0.5)
                        if cls._tunnel_url:
                            cls._status = "active"
                            break

                    if not cls._tunnel_url:
                        # URL not captured yet: report honest state, never fake a
                        # public tunnel with the localhost address.
                        cls._tunnel_url = f"http://127.0.0.1:{local_port}"
                        cls._status = "starting"

                    cls._url_is_public = bool(
                        cls._tunnel_url and cls._tunnel_url.startswith("https://")
                    )
                    if cls._url_is_public:
                        cls._status = "active"
                        await cls._persist_provider("cloudflare")
                        cls._ensure_watchdog()
                    return {
                        "status": cls._status,
                        "url": cls._tunnel_url,
                        "provider": "cloudflare",
                        "url_is_public": cls._url_is_public,
                        "message": None if cls._url_is_public else
                        "Tunnel is still negotiating its public URL; retry status in a few seconds.",
                    }
                except Exception as e:
                    logger.error("Failed to start cloudflared tunnel: %s", e)
                    cls._status = "error"

        # 2. Ngrok Provider
        if provider == "ngrok" or (provider == "auto" and shutil.which("ngrok")):
            if shutil.which("ngrok"):
                try:
                    if ngrok_token:
                        proc = await asyncio.create_subprocess_exec(
                            "ngrok", "config", "add-authtoken", ngrok_token,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await proc.wait()

                    cls._process = await asyncio.create_subprocess_exec(
                        "ngrok", "http", str(local_port),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    cls._provider = "ngrok"
                    await asyncio.sleep(2.0)

                    # Query local ngrok API
                    public_url: Optional[str] = None
                    async with aiohttp.ClientSession() as session:
                        async with session.get("http://127.0.0.1:4040/api/tunnels") as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                tunnels = data.get("tunnels") or []
                                if tunnels:
                                    public_url = tunnels[0].get("public_url")

                    if public_url:
                        cls._tunnel_url = public_url
                        cls._url_is_public = public_url.startswith("https://")
                        cls._status = "active"
                        await cls._persist_provider("ngrok")
                        cls._ensure_watchdog()
                        return {
                            "status": "active",
                            "url": cls._tunnel_url,
                            "provider": "ngrok",
                            "url_is_public": cls._url_is_public,
                        }
                except Exception as e:
                    logger.error("Failed to start ngrok tunnel: %s", e)
                    cls._status = "error"

        # 3. Localhost Fallback Mode (For LAN access without external tunnel binary)
        cls._status = "local_only"
        cls._tunnel_url = f"http://127.0.0.1:{local_port}"
        cls._url_is_public = False
        return {
            "status": "local_only",
            "url": cls._tunnel_url,
            "provider": "local",
            "url_is_public": False,
            "message": "Tunnel binary not found on PATH. Accessible via local network only.",
        }

    @classmethod
    async def _read_cloudflared_output(cls):
        """Parse cloudflared stderr output to capture the assigned trycloudflare.com URL."""
        if not cls._process or not cls._process.stderr:
            return

        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        while cls._process and cls._process.returncode is None:
            try:
                line = await cls._process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="ignore")
                match = url_pattern.search(decoded)
                if match:
                    cls._tunnel_url = match.group(0)
                    cls._status = "active"
                    logger.info("Captured Cloudflare Tunnel URL: %s", cls._tunnel_url)
                    break
            except Exception:
                break

    @classmethod
    async def stop_tunnel(cls):
        """Stop active tunnel process."""
        if cls._watchdog_task and not cls._watchdog_task.done():
            cls._watchdog_task.cancel()
            cls._watchdog_task = None

        if cls._read_task and not cls._read_task.done():
            cls._read_task.cancel()
            cls._read_task = None

        if cls._process:
            try:
                cls._process.terminate()
                await cls._process.wait()
            except Exception:
                pass
            finally:
                cls._process = None

        cls._tunnel_url = None
        cls._url_is_public = False
        cls._status = "inactive"
        logger.info("Outbound tunnel stopped.")

    @classmethod
    def get_tunnel_url(cls) -> Optional[str]:
        return cls._tunnel_url

    @classmethod
    def get_status(cls) -> str:
        return cls._status

    @classmethod
    def get_provider(cls) -> str:
        return cls._provider

    @classmethod
    def is_url_public(cls) -> bool:
        return cls._url_is_public

    @classmethod
    def status_snapshot(cls) -> Dict[str, Any]:
        """Honest status snapshot for the parent portal UI."""
        return {
            "status": cls._status,
            "url": cls._tunnel_url,
            "provider": cls._provider,
            "url_is_public": cls._url_is_public,
            "restart_attempts": cls._restart_attempts,
        }

    # -------------------------------------------------- resilience / persistence

    @staticmethod
    async def _persist_provider(provider: str) -> None:
        """Remember the chosen provider so restarts reuse it."""
        try:
            import time

            import aiosqlite

            from deeptutor.services.path_service import get_path_service
            from deeptutor.services.remote.kv_settings import ensure_kv_settings

            db_path = get_path_service().user_dir / "chat_history.db"
            async with aiosqlite.connect(db_path) as db:
                await ensure_kv_settings(db)
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES ('tunnel_provider', ?, 'parent_security', ?)",
                    (provider, time.time()),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            logger.debug("Could not persist tunnel provider: %s", exc)

    @classmethod
    def _ensure_watchdog(cls) -> None:
        if cls._watchdog_task and not cls._watchdog_task.done():
            return
        cls._restart_attempts = 0
        cls._watchdog_task = asyncio.create_task(cls._watchdog_loop())

    @classmethod
    async def _watchdog_loop(cls):
        """Auto-restart the tunnel process if it dies (URL rotates on cloudflared)."""
        while True:
            await asyncio.sleep(15)
            try:
                if cls._status != "active" or not cls._process:
                    continue
                if cls._process.returncode is None:
                    continue
                if cls._restart_attempts >= 3:
                    cls._status = "failed"
                    logger.warning("Tunnel watchdog giving up after 3 restart attempts.")
                    return
                cls._restart_attempts += 1
                cls._status = "reconnecting"
                logger.info("Tunnel died; restarting (attempt %d)...", cls._restart_attempts)
                result = await cls.start_tunnel(
                    local_port=cls._last_port,
                    provider=cls._provider,
                    ngrok_token=cls._last_ngrok_token,
                )
                if result.get("url_is_public"):
                    cls._restart_attempts = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tunnel watchdog iteration failed: %s", exc)
