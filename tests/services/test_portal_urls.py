"""User-friendly tests for Parent Portal URL resolution.

In plain language, every portal link must be honest:
- If a public tunnel is live, links use it (mode "tunnel").
- Otherwise links use the real LAN address of the frontend server
  (mode "lan") — never a localhost guess, never a dead tunnel URL.
"""

from __future__ import annotations

from deeptutor.services.remote import portal_urls as pu
from deeptutor.services.remote import tunnel_gateway as tg


def test_tunnel_mode_wins_when_public(monkeypatch):
    monkeypatch.setattr(
        tg.TunnelGateway, "get_tunnel_url", classmethod(lambda cls: "https://abc.trycloudflare.com")
    )
    monkeypatch.setattr(tg.TunnelGateway, "is_url_public", classmethod(lambda cls: True))
    url, mode = pu.portal_base_url()
    assert (url, mode) == ("https://abc.trycloudflare.com", "tunnel")
    assert pu.public_tunnel_url() == "https://abc.trycloudflare.com"


def test_non_public_tunnel_falls_back_to_lan(monkeypatch):
    """A tunnel URL that is not public must never be presented as reachable."""
    monkeypatch.setattr(
        tg.TunnelGateway, "get_tunnel_url", classmethod(lambda cls: "http://127.0.0.1:4040")
    )
    monkeypatch.setattr(tg.TunnelGateway, "is_url_public", classmethod(lambda cls: False))
    assert pu.public_tunnel_url() is None
    url, mode = pu.portal_base_url()
    assert mode == "lan", f"expected lan fallback, got {url}"
    assert url.startswith("http://") and "/parent" not in url


def test_lan_url_uses_configured_frontend_port(monkeypatch):
    monkeypatch.setattr(tg.TunnelGateway, "get_tunnel_url", classmethod(lambda cls: None))
    monkeypatch.setattr(pu, "frontend_port", lambda: 3999)
    monkeypatch.setattr(pu, "lan_ip", lambda: "192.168.1.50")
    url, mode = pu.portal_base_url()
    assert (url, mode) == ("http://192.168.1.50:3999", "lan")
    assert pu.lan_dashboard_url() == "http://192.168.1.50:3999/parent"


def test_frontend_port_falls_back_honestly(monkeypatch):
    """When settings are unavailable pre-init, the known default is used."""
    import deeptutor.services.setup as setup

    monkeypatch.setattr(setup, "get_frontend_port", lambda: (_ for _ in ()).throw(RuntimeError("nope")))
    assert pu.frontend_port() == pu.FRONTEND_PORT_FALLBACK == 3782


def test_lan_ip_never_raises():
    ip = pu.lan_ip()
    assert isinstance(ip, str) and len(ip.split(".")) == 4, f"not an IPv4 address: {ip!r}"
