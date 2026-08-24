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
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Official Cloudflare release asset for Windows x86_64 (no account needed).
_CLOUDFLARED_DOWNLOAD_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)
# A truncated/corrupted download must never be executed.
_CLOUDFLARED_MIN_BYTES = 5 * 1024 * 1024  # ~18 MB real binary
_DOWNLOAD_TIMEOUT_S = 180


class TunnelGateway:
    """Manages outbound encrypted tunnel processes for parent remote access."""

    _process: Optional[asyncio.subprocess.Process] = None
    _tunnel_url: Optional[str] = None
    _status: str = "inactive"
    _provider: str = "cloudflare"
    _read_task: Optional[asyncio.Task] = None
    _url_is_public: bool = False
    _watchdog_task: Optional[asyncio.Task] = None
    _last_port: Optional[int] = None
    _last_ngrok_token: Optional[str] = None
    _restart_attempts: int = 0
    _last_message: Optional[str] = None

    @staticmethod
    def _default_local_port() -> int:
        """Tunnels must front the FRONTEND server (which proxies /api to the
        backend), so a public {tunnel}/parent URL serves the real portal UI.
        Falls back to the documented default frontend port."""
        try:
            from deeptutor.services.setup import get_frontend_port

            return int(get_frontend_port())
        except Exception:  # noqa: BLE001 - settings unavailable pre-init
            return 3782

    @classmethod
    def get_local_port(cls) -> int:
        """Port the active (or last-configured) tunnel forwards to."""
        return int(cls._last_port or cls._default_local_port())

    # -------------------------------------------------- binary provisioning

    @staticmethod
    def _managed_bin_dir() -> Path:
        """Managed tools dir inside per-user data (survives app updates)."""
        try:
            from deeptutor.services.path_service import get_path_service

            d = Path(get_path_service().user_dir) / "bin"
        except Exception:  # noqa: BLE001 - path service unavailable (tests)
            d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AI Guru" / "bin"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def _resolve_cloudflared(cls) -> Optional[str]:
        """Absolute path to a usable cloudflared binary, or None.

        Order: PATH → managed bin dir (previous auto-download).
        """
        found = shutil.which("cloudflared")
        if found:
            return found
        managed = cls._managed_bin_dir() / "cloudflared.exe"
        if managed.is_file() and managed.stat().st_size >= _CLOUDFLARED_MIN_BYTES:
            return str(managed)
        return None

    @staticmethod
    def _cloudflared_download_url() -> str:
        return _CLOUDFLARED_DOWNLOAD_URL

    @classmethod
    async def _ensure_cloudflared(cls, progress=None) -> str:
        """Return a usable cloudflared path, downloading it once if needed.

        ``progress`` is an optional callable receiving short human-readable
        stage strings so the parent UI can show honest feedback.
        """
        resolved = cls._resolve_cloudflared()
        if resolved:
            return resolved

        def _say(msg: str) -> None:
            cls._last_message = msg
            if progress:
                try:
                    progress(msg)
                except Exception:  # noqa: BLE001 - UI callback must never break us
                    pass
            logger.info("%s", msg)

        _say("Tunnel engine not found — downloading cloudflared once…")
        target = cls._managed_bin_dir() / "cloudflared.exe"
        part = target.with_suffix(".exe.part")
        timeout = aiohttp.ClientTimeout(total=_DOWNLOAD_TIMEOUT_S)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(cls._cloudflared_download_url()) as resp:
                    if resp.status != 200:
                        raise RuntimeError(
                            f"Download failed: HTTP {resp.status} from Cloudflare releases."
                        )
                    received = 0
                    with open(part, "wb") as fh:
                        async for chunk in resp.content.iter_chunked(1 << 16):
                            fh.write(chunk)
                            received += len(chunk)
            if received < _CLOUDFLARED_MIN_BYTES:
                raise RuntimeError(
                    f"Downloaded file too small ({received} bytes) — refusing to run it."
                )
            os.replace(part, target)
            _say("Tunnel engine ready.")
            return str(target)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced honestly to the UI
            logger.error("cloudflared provisioning failed: %s", exc)
            try:
                if part.exists():
                    part.unlink()
            except OSError:
                pass
            raise RuntimeError(f"Could not provision the cloudflared tunnel engine: {exc}") from exc

    @classmethod
    async def start_tunnel(
        cls,
        local_port: Optional[int] = None,
        provider: str = "cloudflare",
        ngrok_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start the selected outbound tunnel gateway.

        ``local_port`` defaults to the configured FRONTEND port — never the
        raw API port — so remote parents land on the actual portal UI.
        """
        if local_port is None:
            local_port = cls._default_local_port()
        local_port = int(local_port)

        if (
            cls._process
            and cls._process.returncode is None
            and cls._status == "active"
            and cls._tunnel_url
        ):
            # Healthy AND alive: report the existing tunnel. Without the
            # returncode check, a dead process with stale status/url would
            # short-circuit here forever and the watchdog could never restart.
            return {
                "status": "active",
                "url": cls._tunnel_url,
                "provider": cls._provider,
                "url_is_public": cls._url_is_public,
            }

        if cls._process and cls._process.returncode is None:
            # A previous attempt is still negotiating ("starting"). Kill it
            # before spawning a replacement, or we leak orphan processes.
            try:
                cls._process.terminate()
                await cls._process.wait()
            except Exception:  # noqa: BLE001 - process may have just exited
                pass
        cls._tunnel_url = None
        cls._url_is_public = False
        cls._last_message = None

        cls._last_port = local_port
        cls._last_ngrok_token = ngrok_token or cls._last_ngrok_token
        cls._restart_attempts = 0
        cls._status = "starting"
        cls._provider = provider

        # 1. Cloudflare Quick Tunnel (Recommended, No Account Required).
        # The binary is auto-provisioned on first use, so an explicit
        # cloudflare/auto request never silently degrades to LAN-only just
        # because no executable was pre-installed.
        if provider in ("cloudflare", "auto"):
            exe_path: Optional[str] = None
            try:
                exe_path = await cls._ensure_cloudflared()
            except asyncio.CancelledError:
                raise
            except RuntimeError as e:
                logger.error("cloudflared unavailable: %s", e)
                cls._status = "error"
                cls._last_message = str(e)

            if exe_path and shutil.which(exe_path) is None and not Path(exe_path).is_file():
                # Defensive: resolved path vanished between check and exec.
                cls._status = "error"
                cls._last_message = f"Tunnel engine disappeared unexpectedly: {exe_path}"
                exe_path = None

            if exe_path:
                try:
                    cmd = [exe_path, "tunnel", "--url", f"http://127.0.0.1:{local_port}"]
                    cls._process = await asyncio.create_subprocess_exec(
                        *cmd,
                        # stdout is never parsed — DEVNULL so its buffer can
                        # never fill and block the child process mid-tunnel.
                        # stderr carries the URL and is drained continuously
                        # by _read_cloudflared_output for the process lifetime.
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    cls._status = "starting"
                    cls._provider = "cloudflare"
                    cls._last_message = None

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
                        "message": cls._last_message
                        or (
                            None
                            if cls._url_is_public
                            else "Tunnel is still negotiating its public URL; retry status in a few seconds."
                        ),
                    }
                except Exception as e:
                    logger.error("Failed to start cloudflared tunnel: %s", e)
                    cls._status = "error"
                    cls._last_message = f"Failed to launch cloudflared: {e}"

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

        # 3. Honest failure — an explicitly requested tunnel must never be
        # dressed up as a working LAN-only mode.
        if cls._status == "error":
            return {
                "status": "error",
                "url": None,
                "provider": cls._provider,
                "url_is_public": False,
                "message": cls._last_message or "Tunnel could not be started.",
            }

        # 4. Localhost Fallback Mode (For LAN access without external tunnel binary)
        cls._status = "local_only"
        cls._tunnel_url = f"http://127.0.0.1:{local_port}"
        cls._url_is_public = False
        cls._last_message = (
            "Tunnel gateway not available on this machine. "
            "Accessible via local network only."
        )
        return {
            "status": "local_only",
            "url": cls._tunnel_url,
            "provider": "local",
            "url_is_public": False,
            "message": cls._last_message,
        }

    @classmethod
    async def _read_cloudflared_output(cls):
        """Drain cloudflared stderr for the process lifetime, capturing the URL.

        The reader must NOT stop after the URL is found: cloudflared keeps
        writing to stderr, and an undrained OS pipe fills (~64 KB) and blocks
        the child mid-tunnel — the exact "tunnel silently stalls" failure.
        """
        if not cls._process or not cls._process.stderr:
            return

        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        while cls._process and cls._process.returncode is None:
            try:
                line = await cls._process.stderr.readline()
                if not line:
                    break  # EOF: process is exiting
                if cls._tunnel_url and cls._tunnel_url.startswith("https://"):
                    continue  # URL captured; keep draining, stop matching
                decoded = line.decode("utf-8", errors="ignore")
                match = url_pattern.search(decoded)
                if match:
                    cls._tunnel_url = match.group(0)
                    cls._status = "active"
                    logger.info("Captured Cloudflare Tunnel URL: %s", cls._tunnel_url)
            except asyncio.CancelledError:
                raise
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
        cls._last_message = None
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
            "message": cls._last_message,
            "restart_attempts": cls._restart_attempts,
            "local_port": cls.get_local_port(),
            "portal_hint": (
                f"{cls._tunnel_url}/parent"
                if cls._tunnel_url and cls._url_is_public
                else None
            ),
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
                    cls._last_message = (
                        "Tunnel kept dropping — gave up after 3 automatic restarts. "
                        "Press Start Tunnel to try again."
                    )
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
                elif result.get("status") == "error":
                    cls._status = "failed"
                    cls._last_message = (
                        result.get("message") or cls._last_message or "Tunnel restart failed."
                    )
                    logger.warning("Tunnel watchdog restart failed: %s", cls._last_message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tunnel watchdog iteration failed: %s", exc)
