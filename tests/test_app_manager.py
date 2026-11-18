"""Globe lifecycle uses workspace dependencies and only owns its child."""

import subprocess
from unittest.mock import Mock

from core import app_manager


def test_globe_start_uses_hoisted_vite(tmp_path, monkeypatch):
    folder = tmp_path / 'apps' / 'gods-eye-view'
    folder.mkdir(parents=True)
    vite = tmp_path / 'node_modules' / 'vite' / 'bin' / 'vite.js'
    vite.parent.mkdir(parents=True)
    vite.touch()
    monkeypatch.setattr(app_manager, 'BASE_DIR', tmp_path)
    monkeypatch.setenv('GODS_EYE_VIEW_DIR', str(folder))
    monkeypatch.setattr(app_manager, '_processes', {'gev': None})
    monkeypatch.setattr(app_manager, '_is_port_open', lambda _: False)
    monkeypatch.setattr(app_manager.shutil, 'which', lambda name: '/bin/node' if name == 'node' else None)
    ready = Mock(return_value=True)
    monkeypatch.setattr(app_manager, '_wait_for_service', ready)
    child = Mock()
    spawn = Mock(return_value=child)
    monkeypatch.setattr(app_manager.subprocess, 'Popen', spawn)

    assert app_manager.AppManager.start_gev()['status'] == 'started'
    spawn.assert_called_once_with(
        ['/bin/node', str(vite), '--host', '127.0.0.1', '--port', '4174', '--strictPort'], cwd=folder,
    )
    ready.assert_called_once_with(app_manager.GEV_URL, process=child)


def test_globe_stop_never_signals_an_unmanaged_process(monkeypatch):
    child = Mock()
    child.poll.return_value = None
    child.wait.side_effect = [subprocess.TimeoutExpired('node', 3), 0]
    monkeypatch.setattr(app_manager, '_processes', {'gev': child})
    external = Mock(side_effect=AssertionError('must not invoke a process-killing command'))
    monkeypatch.setattr(app_manager.subprocess, 'run', external)

    assert app_manager.AppManager.stop_gev()['status'] == 'stopped'
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
    assert app_manager.AppManager.stop_gev()['status'] == 'not_managed'
    external.assert_not_called()
