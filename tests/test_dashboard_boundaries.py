"""KD network boundary regression checks, without live listeners."""
from types import SimpleNamespace

import pytest

from dashboard.server import _bind_host, _origin_allowed


def test_default_loopback(monkeypatch):
    monkeypatch.delenv("KD_BIND_HOST", raising=False)
    assert _bind_host() == "127.0.0.1"


def test_lan_requires_opt_in(monkeypatch):
    monkeypatch.setenv("KD_BIND_HOST", "0.0.0.0")
    monkeypatch.delenv("KD_ALLOW_LAN", raising=False)
    with pytest.raises(ValueError, match="KD_ALLOW_LAN"):
        _bind_host()
    monkeypatch.setenv("KD_ALLOW_LAN", "1")
    assert _bind_host() == "0.0.0.0"


@pytest.mark.parametrize("origin,allowed", [
    ("https://localhost:8001", True),
    ("https://attacker.invalid", False),
    ("null", False),
    ("https://localhost:8001@attacker.invalid", False),
])
def test_websocket_origin(origin, allowed):
    ws = SimpleNamespace(headers={"host": "localhost:8001", "origin": origin})
    assert _origin_allowed(ws) is allowed


def test_download_without_token_is_unauthorized():
    from fastapi.testclient import TestClient
    from dashboard.server import DashboardServer
    with TestClient(DashboardServer().app) as client:
        assert client.get("/uploads/nonexistent.txt").status_code == 401


def test_main_websocket_rejects_foreign_origin():
    import time
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from dashboard.server import DashboardServer
    server = DashboardServer()
    server._tokens["test-token"] = time.time()
    with TestClient(server.app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?token=test-token", headers={"origin": "https://foreign.invalid"}):
                pytest.fail("Foreign origin accepted")

def test_advertised_host_used_for_docker_links(monkeypatch):
    from dashboard.server import _local_ip, DashboardServer
    monkeypatch.setenv('KD_ADVERTISE_HOST', '10.0.0.10')
    monkeypatch.setattr(DashboardServer, '_ssl_enabled', staticmethod(lambda: True))
    assert _local_ip() == '10.0.0.10'
    assert DashboardServer().get_url() == 'https://10.0.0.10:8001'


@pytest.mark.parametrize('address', ['0.0.0.0', '224.0.0.1', 'https://example.com', 'invalid'])
def test_invalid_advertised_address_rejected(monkeypatch, address):
    from dashboard.server import _local_ip
    monkeypatch.setenv('KD_ADVERTISE_HOST', address)
    with pytest.raises(ValueError):
        _local_ip()
