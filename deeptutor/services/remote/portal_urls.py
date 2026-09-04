"""Single home for Parent Portal URL resolution.

Three copies of this logic drifted across the codebase (parent router,
notification outbox, Telegram command listener) with subtly different
fallbacks. Every portal link — Telegram alerts, send-link, live-stream
replies, LAN hints — now resolves through here:

- Public tunnel URL when (and only when) it is actually public.
- Otherwise the honest LAN address of the FRONTEND server (which proxies
  /api to the backend). Never a fabricated localhost guess, never a
  non-public tunnel URL presented as reachable.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

FRONTEND_PORT_FALLBACK = 3782


def frontend_port() -> int:
    """Configured frontend port (serves the portal UI remotely)."""
    try:
        from deeptutor.services.setup import get_frontend_port

        return int(get_frontend_port())
    except Exception:  # noqa: BLE001 - settings unavailable pre-init
        return FRONTEND_PORT_FALLBACK


def lan_ip() -> str:
    """Best-effort primary LAN IPv4 (loopback fallback; never raises)."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.0)
    try:
        s.connect(("8.8.8.8", 80))
        return str(s.getsockname()[0])
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def public_tunnel_url() -> Optional[str]:
    """Live public tunnel base URL, or None when LAN-only/offline (honest)."""
    try:
        from deeptutor.services.remote.tunnel_gateway import TunnelGateway

        base = TunnelGateway.get_tunnel_url()
        if base and TunnelGateway.is_url_public():
            return str(base)
    except Exception:  # noqa: BLE001 - link is an enhancement, never a failure
        pass
    return None


def portal_base_url() -> Tuple[str, str]:
    """(base_url, mode) for the parent portal link.

    ``mode`` is ``"tunnel"`` when the URL is publicly reachable, else
    ``"lan"`` with the frontend's LAN address.
    """
    tunnel_url = public_tunnel_url()
    if tunnel_url:
        return tunnel_url, "tunnel"
    return f"http://{lan_ip()}:{frontend_port()}", "lan"


def lan_dashboard_url() -> Optional[str]:
    """LAN-accessible ``/parent`` URL, or None when undiscoverable."""
    try:
        return f"http://{lan_ip()}:{frontend_port()}/parent"
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "FRONTEND_PORT_FALLBACK",
    "frontend_port",
    "lan_ip",
    "public_tunnel_url",
    "portal_base_url",
    "lan_dashboard_url",
]
