"""TunnelGateway binary-provisioning + honest-status tests.

Covers the zero-config cloudflared auto-download path introduced after the
"Start Tunnel did nothing" report: neither cloudflared nor ngrok existed on
the machine, so every start silently degraded to local_only with no reason
surfaced to the parent UI.

Isolation strategy: no real network, no real processes. The HTTP layer is
replaced by an in-memory fake ``aiohttp.ClientSession`` and class state is
reset between tests so host-machine binaries can never influence results.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.remote import tunnel_gateway as tg_mod
from deeptutor.services.remote.tunnel_gateway import TunnelGateway

# ------------------------------------------------------------ fakes


class _FakeContent:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def iter_chunked(self, size: int):
        for i in range(0, len(self._payload), size):
            yield self._payload[i : i + size]


class _FakeResponse:
    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self.content = _FakeContent(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Minimal stand-in for aiohttp.ClientSession (context manager + get)."""

    last_url: str | None = None
    response_status: int = 200
    response_payload: bytes = b""

    def __init__(self, *args, **kwargs) -> None:  # timeout kwarg ignored
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url: str) -> _FakeResponse:
        type(self).last_url = url
        return _FakeResponse(type(self).response_status, type(self).response_payload)


def _install_fake_http(monkeypatch, *, status: int = 200, payload: bytes | None = None):
    _FakeSession.last_url = None
    _FakeSession.response_status = status
    if payload is None:
        # Realistic minimum-size binary blob (passes the 5 MB sanity gate).
        payload = b"MZ" + b"\x00" * (6 * 1024 * 1024)
    _FakeSession.response_payload = payload
    monkeypatch.setattr(tg_mod.aiohttp, "ClientSession", _FakeSession)


# ------------------------------------------------------------ fixtures


@pytest.fixture()
def gateway(tmp_path: Path, monkeypatch):
    """Fresh TunnelGateway class state + temp managed bin dir per test."""
    tg = tg_mod.TunnelGateway
    tg._process = None
    tg._tunnel_url = None
    tg._url_is_public = False
    tg._status = "inactive"
    tg._provider = "cloudflare"
    tg._read_task = None
    tg._watchdog_task = None
    tg._restart_attempts = 0
    tg._last_port = None
    tg._last_ngrok_token = None
    tg._last_message = None

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(tg_mod.TunnelGateway, "_managed_bin_dir", staticmethod(lambda: bin_dir))
    monkeypatch.setattr(tg_mod.shutil, "which", lambda name: None)
    return tg


# ------------------------------------------------------------ resolution


class TestResolveCloudflared:
    def test_returns_none_when_nothing_installed(self, gateway):
        assert gateway._resolve_cloudflared() is None

    def test_prefers_path_hit(self, gateway, monkeypatch):
        monkeypatch.setattr(
            tg_mod.shutil,
            "which",
            lambda name: r"C:\tools\cloudflared.exe" if name == "cloudflared" else None,
        )
        assert gateway._resolve_cloudflared() == r"C:\tools\cloudflared.exe"

    def test_falls_back_to_managed_binary_when_big_enough(self, gateway):
        managed = gateway._managed_bin_dir() / "cloudflared.exe"
        managed.write_bytes(b"MZ" + b"\x00" * (6 * 1024 * 1024))
        assert gateway._resolve_cloudflared() == str(managed)

    def test_rejects_undersized_managed_binary(self, gateway):
        """A truncated/corrupt previous download must never be executed."""
        managed = gateway._managed_bin_dir() / "cloudflared.exe"
        managed.write_bytes(b"corrupt")
        assert gateway._resolve_cloudflared() is None


# ------------------------------------------------------------ provisioning


class TestEnsureCloudflared:
    @pytest.mark.asyncio
    async def test_downloads_into_managed_dir(self, gateway, monkeypatch):
        _install_fake_http(monkeypatch)
        stages: list[str] = []
        path = await gateway._ensure_cloudflared(progress=stages.append)

        target = gateway._managed_bin_dir() / "cloudflared.exe"
        assert path == str(target)
        assert target.is_file()
        assert target.stat().st_size >= tg_mod._CLOUDFLARED_MIN_BYTES
        assert not target.with_suffix(".exe.part").exists(), "temp file must be consumed"
        assert any("downloading" in s.lower() for s in stages)
        assert "cloudflared-windows-amd64.exe" in (_FakeSession.last_url or "")

    @pytest.mark.asyncio
    async def test_second_call_skips_download(self, gateway, monkeypatch):
        _install_fake_http(monkeypatch)
        await gateway._ensure_cloudflared()
        again = await gateway._ensure_cloudflared()
        assert again.endswith("cloudflared.exe")
        assert gateway._resolve_cloudflared() == again

    @pytest.mark.asyncio
    async def test_http_failure_is_honest(self, gateway, monkeypatch):
        _install_fake_http(monkeypatch, status=503)
        with pytest.raises(RuntimeError, match="HTTP 503"):
            await gateway._ensure_cloudflared()
        assert gateway._last_message  # surfaced for the UI
        assert not (gateway._managed_bin_dir() / "cloudflared.exe.part").exists()

    @pytest.mark.asyncio
    async def test_truncated_payload_refused_and_cleaned(self, gateway, monkeypatch):
        _install_fake_http(monkeypatch, payload=b"MZ-truncated")
        with pytest.raises(RuntimeError, match="too small"):
            await gateway._ensure_cloudflared()
        bin_dir = gateway._managed_bin_dir()
        assert not (bin_dir / "cloudflared.exe").exists()
        assert not (bin_dir / "cloudflared.exe.part").exists()


# ------------------------------------------------------------ start_tunnel


class TestStartTunnelHonesty:
    @pytest.mark.asyncio
    async def test_explicit_cloudflare_provision_failure_returns_error(self, gateway, monkeypatch):
        """A requested tunnel must never masquerade as healthy LAN-only mode."""

        async def _boom(progress=None):
            raise RuntimeError("Could not provision the cloudflared tunnel engine: offline")

        monkeypatch.setattr(tg_mod.TunnelGateway, "_ensure_cloudflared", classmethod(_boom))
        result = await gateway.start_tunnel(provider="cloudflare")

        assert result["status"] == "error"
        assert result["url"] is None
        assert result["url_is_public"] is False
        assert "provision" in (result.get("message") or "").lower()
        assert gateway._status == "error"

    @pytest.mark.asyncio
    async def test_ngrok_missing_reports_local_only_with_reason(self, gateway):
        result = await gateway.start_tunnel(provider="ngrok")

        assert result["status"] == "local_only"
        assert result["url_is_public"] is False
        assert result.get("message"), "fallback must explain itself"
        assert gateway._last_message == result["message"]

    @pytest.mark.asyncio
    async def test_auto_provisions_then_launches_cloudflare(self, gateway, monkeypatch):
        """Happy path: provisioning resolves a path, process spawns, URL captured."""
        exe = gateway._managed_bin_dir() / "cloudflared.exe"
        exe.write_bytes(b"MZ" + b"\x00" * (6 * 1024 * 1024))

        class _FakeProc:
            returncode = 0  # already exited → reader loop ends instantly
            stderr = None

        spawned: list[list] = []

        async def _fake_exec(*args, **kwargs):
            spawned.append(list(args))
            return _FakeProc()

        async def _seed_url():
            # Simulates the stderr reader capturing the trycloudflare URL.
            gateway._tunnel_url = "https://demo.trycloudflare.com"
            gateway._status = "active"

        async def _noop(*args, **kwargs):
            return None

        monkeypatch.setattr(
            tg_mod.TunnelGateway,
            "_ensure_cloudflared",
            classmethod(lambda cls, progress=None: _return(str(exe))),
        )
        monkeypatch.setattr(tg_mod.asyncio, "create_subprocess_exec", _fake_exec)
        monkeypatch.setattr(
            tg_mod.TunnelGateway, "_read_cloudflared_output", classmethod(lambda cls: _seed_url())
        )
        monkeypatch.setattr(tg_mod.TunnelGateway, "_persist_provider", classmethod(_noop))
        monkeypatch.setattr(tg_mod.TunnelGateway, "_ensure_watchdog", classmethod(lambda cls: None))

        result = await gateway.start_tunnel(provider="cloudflare")

        assert result["status"] == "active"
        assert result["url_is_public"] is True
        assert result["url"].endswith(".trycloudflare.com")
        assert spawned and str(exe) == spawned[0][0], "must exec the resolved absolute path"


# ------------------------------------------------------------ snapshot


class TestStatusSnapshot:
    def test_snapshot_exposes_message_for_polling_ui(self, gateway):
        gateway._status = "error"
        gateway._last_message = "Could not provision the engine."
        snap = gateway.status_snapshot()
        assert snap["message"] == "Could not provision the engine."
        assert snap["status"] == "error"

    def test_snapshot_message_none_when_quiet(self, gateway):
        snap = gateway.status_snapshot()
        assert snap["message"] is None


# ------------------------------------------------------------ helpers


async def _return(value):
    return value
