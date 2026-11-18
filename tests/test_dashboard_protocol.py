"""Authenticated redesigned-dashboard contract, without hardware or network."""
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dashboard.server import DashboardServer


@pytest.fixture
def paired():
    server = DashboardServer()
    server._tokens['test-session'] = time.time()
    with TestClient(server.app) as client:
        yield server, client, {'Authorization': 'Bearer test-session'}


def test_telemetry_requires_pairing(paired):
    _, client, headers = paired
    assert client.get('/api/telemetry').status_code == 401
    response = client.get('/api/telemetry', headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json()['cpu'], (int, float))


def test_feature_catalog_requires_pairing_and_reports_live_inventory(paired):
    server, client, headers = paired
    server.set_feature_catalog(lambda: [
        {"name": "calculator", "description": "Evaluates maths", "file": "calculator.py",
         "valid": True, "enabled": True, "kind": "plugin"},
        {"name": "broken", "description": "", "file": "broken.py",
         "valid": False, "enabled": False, "kind": "action", "error": "Missing handler"},
    ])
    assert client.get('/api/features').status_code == 401
    response = client.get('/api/features', headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == 2
    assert payload['active'] == 1
    assert payload['features'][1]['error'] == 'Missing handler'


def test_feature_catalog_reports_provider_failure(paired):
    server, client, headers = paired
    server.set_feature_catalog(lambda: (_ for _ in ()).throw(RuntimeError('catalog failed')))
    payload = client.get('/api/features', headers=headers).json()
    assert payload['total'] == 1
    assert payload['active'] == 0
    assert payload['features'][0]['error'] == 'catalog failed'


def test_command_and_wake_contract(paired):
    server, client, headers = paired
    server._wake_callback = Mock()
    assert client.post('/api/command', json={'text': 'hello'}).status_code == 401
    assert client.post('/api/command', headers=headers, json={'text': 'hello'}).json()['ok']
    assert server._command_queue.get_nowait() == 'hello'
    client.post('/api/wake', headers=headers)
    assert server._wake_callback.call_count == 2


def test_authenticated_websocket_history(paired):
    server, client, _ = paired
    server._history.append({'type': 'log', 'speaker': 'jarvis', 'text': 'ready'})
    with client.websocket_connect('/ws?token=test-session') as ws:
        assert ws.receive_json()['text'] == 'ready'


def test_websocket_rechecks_revoked_token(paired):
    server, client, _ = paired
    with client.websocket_connect('/ws?token=test-session') as ws:
        server._tokens.clear()
        ws.send_json({'type': 'command', 'text': 'must not execute'})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert server._command_queue.empty()


def test_gesture_authentication_and_processing(paired, monkeypatch):
    import cv2
    import numpy as np
    server, client, _ = paired
    tracker = Mock()
    tracker.process.return_value = []
    monkeypatch.setattr('core.gesture_3d.MediaPipeHandTracker', lambda: tracker)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/gestures?token=invalid'):
            pass
    _, encoded = cv2.imencode('.jpg', np.zeros((240, 320, 3), dtype=np.uint8))
    with client.websocket_connect('/ws/gestures?token=test-session') as ws:
        assert ws.receive_json() == {'ready': True}
        ws.send_bytes(encoded.tobytes())
        assert ws.receive_json() == {'events': []}
    tracker.close.assert_called_once()


def test_gesture_rejects_oversized_frames(paired, monkeypatch):
    _, client, _ = paired
    monkeypatch.setattr('core.gesture_3d.MediaPipeHandTracker', Mock())
    with client.websocket_connect('/ws/gestures?token=test-session') as ws:
        ws.receive_json()
        ws.send_bytes(b'x' * 300001)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1009

# ── /api/new-key ────────────────────────────────────────────────────────────

def test_new_key_endpoint(monkeypatch):
    """POST /api/new-key returns a fresh 8-character pairing key."""
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient

    server = DashboardServer()
    with TestClient(server.app) as client:
        response = client.post("/api/new-key")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert isinstance(data["key"], str)
        assert len(data["key"]) == 8
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789" for c in data["key"])
        assert data["expires_in"] == 600
        assert data["url"].startswith("http")
        assert data["auto_login_url"].endswith(f"/auto-login?key={data['key']}")

        # Key should be usable for login
        login_response = client.post(
            "/login", json={"pin": data["key"]}
        )
        assert login_response.status_code == 200
        assert login_response.json()["ok"] is True

        # Key is single-use
        login_response2 = client.post(
            "/login", json={"pin": data["key"]}
        )
        assert login_response2.status_code == 401
