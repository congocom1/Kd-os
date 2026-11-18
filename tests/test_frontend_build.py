"""The server UI must survive clean Vite builds."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_server_pages_and_offline_assets_are_preserved():
    for name in ('app.html', 'login.html', 'crypto-js.min.js',
                 'fonts/Orbitron-Variable.ttf', 'fonts/Rajdhani-Medium.ttf',
                 'fonts/Rajdhani-SemiBold.ttf'):
        source = ROOT / 'frontend' / 'public' / name
        built = ROOT / 'dashboard' / 'static' / name
        assert source.is_file()
        assert built.read_bytes() == source.read_bytes()


def test_dashboard_serves_build_assets():
    from fastapi.testclient import TestClient
    from dashboard.server import DashboardServer
    with TestClient(DashboardServer().app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/login').status_code == 200
        assert client.get('/static/dashboard.html').status_code == 200
        assert client.get('/static/fonts/Orbitron-Variable.ttf').status_code == 200
        assert client.get('/static/../../config/api_keys.json').status_code != 200