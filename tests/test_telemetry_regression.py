"""Telemetry auth, origin, snapshot ownership and disconnect regressions."""
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from dashboard import server as module


@pytest.fixture
def paired(monkeypatch):
    snapshot = {"status": "partial", "system": {"cpu_percent": 12},
                "gpu": {"status": "unavailable", "utilization_gpu": None}}
    monkeypatch.setattr(module, "get_telemetry", lambda: snapshot)
    monkeypatch.setattr(module, "TELEMETRY_INTERVAL_S", 0.01)
    server = module.DashboardServer()
    server._tokens['paired'] = time.time()
    with TestClient(server.app) as client:
        yield server, client, snapshot


def test_single_http_route_and_immutable_snapshot(paired):
    server, client, snapshot = paired
    assert len([r for r in server.app.routes if r.path == '/api/telemetry']) == 1
    assert client.get('/api/telemetry').status_code == 401
    response = client.get('/api/telemetry', headers={'Authorization': 'Bearer paired'})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['gpu']['utilization_gpu'] is None
    assert 'last_updated' not in snapshot


@pytest.mark.parametrize('url,origin', [
    ('/ws/telemetry', 'http://testserver'),
    ('/ws/telemetry?token=paired', 'https://foreign.invalid'),
    ('/ws/telemetry?token=paired', 'null'),
])
def test_rejected_handshake(paired, url, origin):
    _, client, _ = paired
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url, headers={'origin': origin}):
            pytest.fail('Unauthorized socket accepted')


@pytest.mark.parametrize('expire', [True, False])
def test_stream_rechecks_expiry_and_revocation(paired, expire):
    server, client, snapshot = paired
    with client.websocket_connect('/ws/telemetry?token=paired', headers={'origin': 'http://testserver'}) as ws:
        assert ws.receive_json()['system']['cpu_percent'] == 12
        if expire:
            server._tokens['paired'] = time.time() - module._TOKEN_TTL_SECONDS - 1
        else:
            server._tokens.clear()
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_json()
        assert exc.value.code == 4001
    assert 'last_updated' not in snapshot


def test_clean_disconnect_and_reconnect(paired):
    _, client, _ = paired
    for _ in range(2):
        with client.websocket_connect('/ws/telemetry?token=paired') as ws:
            assert ws.receive_json()['status'] == 'partial'


def test_http_and_websocket_reuse_a_probe(monkeypatch):
    calls = 0
    def collect():
        nonlocal calls
        calls += 1
        return {'system': {'cpu_percent': 12}}

    monkeypatch.setattr(module, 'get_telemetry', collect)
    monkeypatch.setattr(module, 'TELEMETRY_INTERVAL_S', 60)
    server = module.DashboardServer()
    server._tokens['paired'] = time.time()
    with TestClient(server.app) as client:
        assert client.get('/api/telemetry').status_code == 401
        assert calls == 0
        with client.websocket_connect('/ws/telemetry?token=paired') as ws:
            stream = ws.receive_json()
            http = client.get('/api/telemetry', headers={'Authorization': 'Bearer paired'})
            assert http.status_code == 200
            assert http.json() == {**stream, 'cpu': 12}
        assert calls == 1


def test_actual_served_page_has_telemetry_controls(paired):
    _, client, _ = paired
    response = client.get('/')
    assert response.status_code == 200
    assert 'id="telemetryStatus"' in response.text
    assert 'id="telemetryReconnect"' in response.text
    assert '/static/assets/dashboard-' in response.text