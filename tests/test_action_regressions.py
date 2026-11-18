"""Regression tests for action persistence and notification delivery."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_background_monitor_persists_through_memory_manager(monkeypatch, tmp_path):
    """Monitored topics must be stored through the memory manager's writer."""
    from actions import background_monitor
    from memory import memory_manager

    memory_path = tmp_path / "long_term.json"
    monkeypatch.setattr(memory_manager, "MEMORY_PATH", memory_path)
    monkeypatch.setattr(background_monitor, "_load", lambda: {})

    background_monitor.add_monitor("space news")

    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    assert saved["monitors"]["space_news"]["topic"] == "space news"


def test_background_monitor_remove_round_trip(monkeypatch, tmp_path):
    """Removing a monitor must persist the updated monitor collection."""
    from actions import background_monitor
    from memory import memory_manager

    memory_path = tmp_path / "long_term.json"
    monkeypatch.setattr(memory_manager, "MEMORY_PATH", memory_path)
    monkeypatch.setattr(
        background_monitor,
        "_load",
        lambda: {
            "space_news": {
                "topic": "space news",
                "added": "2026-01-01",
            }
        },
    )

    result = background_monitor.remove_monitor("space news")

    assert result == "Stopped monitoring: space news"
    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    assert saved["monitors"] == {}


def test_notification_service_delivers_to_player_and_persists(
    monkeypatch, tmp_path
):
    """A notification must reach the HUD player and the on-disk queue."""
    from actions import notification_service

    queue_path = tmp_path / "notifications.json"
    monkeypatch.setattr(notification_service, "_NOTIF_PATH", queue_path)

    class FakePlayer:
        def __init__(self):
            self.logs = []

        def write_log(self, message):
            self.logs.append(message)

    player = FakePlayer()
    result = notification_service.run_notification_service(
        {
            "action": "send",
            "title": "Status",
            "message": "All systems normal",
            "priority": "info",
        },
        player=player,
    )

    assert "delivered" in result
    assert player.logs == [
        "[NOTIF] [INFO] Status: All systems normal"
    ]
    saved = json.loads(queue_path.read_text(encoding="utf-8"))
    assert saved[0]["title"] == "Status"
    assert saved[0]["priority"] == "info"


def test_notification_service_without_player_does_not_raise(
    monkeypatch, tmp_path
):
    """Headless notification delivery must not depend on a player object."""
    from actions import notification_service

    monkeypatch.setattr(
        notification_service,
        "_NOTIF_PATH",
        tmp_path / "notifications.json",
    )

    result = notification_service.run_notification_service(
        {"action": "send", "title": "Headless", "message": "OK"}
    )

    assert "delivered" in result


def test_troubleshooting_remediation_logs_permission_failure(monkeypatch, caplog):
    """A failed log cleanup must be logged without masking its exception."""
    from actions import troubleshooting

    class FakeStat:
        st_size = 20 * 1024 * 1024

    class FakeFile:
        name = "large.log"

        def stat(self):
            return FakeStat()

        def unlink(self):
            raise PermissionError("denied")

    class FakeLogDir:
        def exists(self):
            return True

        def glob(self, pattern):
            return [FakeFile()]

    monkeypatch.setattr(
        troubleshooting.psutil,
        "disk_usage",
        lambda path: type("Usage", (), {"percent": 95})(),
    )
    monkeypatch.setattr(troubleshooting, "Path", lambda path: FakeLogDir())

    with caplog.at_level("WARNING"):
        fixes = troubleshooting._auto_remediate()

    assert fixes == []
    assert "Failed to remove log file: denied" in caplog.text
