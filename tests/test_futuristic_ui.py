"""Real Qt widgets, isolated from devices and the application session."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton
from types import SimpleNamespace
from unittest.mock import Mock
from ui import MainWindow

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_header_tracks_actual_state(app):
    owner = SimpleNamespace(_assistant_name='JARVIS', _toggle_drawer=Mock(),
                            _toggle_controls=Mock(), hud=SimpleNamespace())
    header = MainWindow._build_header(owner)
    for state in ['SLEEPING', 'LISTENING', 'SPEAKING', 'MUTED']:
        MainWindow._apply_state(owner, state)
        assert owner._state_badge.text() == state
        assert owner.hud.speaking == (state == 'SPEAKING')
    header.resize(820, 76)
    header.show()
    app.processEvents()
    assert header.grab().width() == 820
    header.close()


def test_composer_keeps_send_actions_and_accessible_labels(app):
    owner = SimpleNamespace(_send=Mock())
    host = QWidget()
    layout = QVBoxLayout(host)
    row = MainWindow._build_input_row(owner)
    layout.addLayout(row)
    assert owner._input.accessibleName() == 'Command or question'
    owner._input.setText('hello')
    owner._input.returnPressed.emit()
    send = next(b for b in host.findChildren(QPushButton) if b.accessibleName() == 'Send command')
    send.click()
    assert owner._send.call_count == 2
    assert owner._input.height() == 42
    host.close()
