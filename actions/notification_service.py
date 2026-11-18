"""
actions/notification_service.py — Notification center with priority routing.

Provides:
  - send_notification(title, message, priority) — send to the user
  - list_notifications() — view the notification queue
  - clear_notifications() — empty the queue

Notifications are queued and delivered via the HUD, voice, and log.
Priorities: info | warning | critical
"""

import json
import time
from pathlib import Path

from core import outcome
from core.lazyimport import installed

_psutil = installed("psutil")
psutil = None
if _psutil:
    import psutil

_NOTIF_PATH = Path.home() / ".jarvis" / "notifications.json"

# Default priority levels
PRIORITY_RANKS = {"info": 0, "warning": 1, "critical": 2}


def _load_queue() -> list[dict]:
    """Load the notification queue from disk."""
    if not _NOTIF_PATH.exists():
        return []
    try:
        data = json.loads(_NOTIF_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_queue(queue: list[dict]) -> None:
    """Persist the notification queue to disk."""
    _NOTIF_PATH.parent.mkdir(parents=True, exist_ok=True)
    _NOTIF_PATH.write_text(
        json.dumps(queue, indent=2), encoding="utf-8"
    )


def _clear_queue() -> None:
    """Empty the notification queue."""
    if _NOTIF_PATH.exists():
        try:
            _NOTIF_PATH.unlink()
        except Exception:
            pass


def _render_title(title: str, priority: str) -> str:
    """Render a priority-tagged title."""
    rank = PRIORITY_RANKS.get(priority, 0)
    markers = {0: "ℹ", 1: "⚠", 2: "🛑"}
    return f"{markers.get(rank, '⚠')} {title}"


def _deliver_notification(
    title: str,
    message: str,
    priority: str,
    player=None,
) -> str:
    """Deliver a notification via all available channels.

    Channels:
      - HUD (player.write_log if available)
      - Voice (player.session.speak if available)
      - Log (print)
      - File (persisted to disk)
    """
    if priority == "critical":
        voice_msg = f"Critical alert: {message}"
    elif priority == "warning":
        voice_msg = f"Warning: {message}"
    else:
        voice_msg = f"Notification: {title}. {message}"

    # Deliver to all available channels. Importing the UI module is optional:
    # notification delivery must still work in headless and service contexts.
    try:
        import asyncio

        async def _speak():
            try:
                await player.session.speak(voice_msg)
            except Exception:
                pass

        if player and hasattr(player, "session") and player.session:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(_speak(), loop)
                else:
                    loop.run_until_complete(_speak())
            except Exception:
                pass
    except Exception:
        pass

    # Always log to HUD and console.
    try:
        print(f"[NOTIF] [{priority.upper()}] {title}")
        if player and hasattr(player, "write_log"):
            player.write_log(f"[NOTIF] [{priority.upper()}] {title}: {message}")
    except Exception:
        print(f"[NOTIF] [{priority.upper()}] {title}: {message}")

    # Persist to disk.
    try:
        queue = _load_queue()
        queue.append(
            {
                "id": int(time.time() * 1000),
                "title": title,
                "message": message,
                "priority": priority,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        _save_queue(queue)
    except Exception:
        pass

    return ""


# ── Action implementations ───────────────────────────────────────────────────


def _list_notifications() -> dict:
    """Return the current notification queue."""
    queue = _load_queue()
    queue_sorted = sorted(queue, key=lambda item: item.get("id", 0), reverse=True)
    return {"count": len(queue_sorted), "notifications": queue_sorted}


def _clear_notifications() -> dict:
    """Clear the notification queue."""
    _clear_queue()
    return {"cleared": True}


# ── Tool declaration ─────────────────────────────────────────────────────────

TOOL = {
    "name": "notification_service",
    "description": (
        "Notification service. Actions: send (send a notification with title, "
        "message, and priority), list (review queued notifications), clear (empty "
        "the queue)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "send | list | clear",
            },
            "title": {"type": "STRING", "description": "Notification title"},
            "message": {"type": "STRING", "description": "Notification message"},
            "priority": {
                "type": "STRING",
                "description": "Priority: info | warning | critical",
            },
        },
        "required": ["action"],
    },
    "handler": None,
}


def run_notification_service(parameters: dict, player=None, session_memory=None) -> str:
    """Handler for the notification_service tool."""
    action = (parameters.get("action") or "").strip().lower()

    if action == "send":
        title = (parameters.get("title") or "JARVIS Notification").strip()
        message = (parameters.get("message") or "").strip()
        priority = (parameters.get("priority") or "info").strip().lower()
        if priority not in ("info", "warning", "critical"):
            priority = "info"

        _deliver_notification(title, message, priority, player=player)
        return outcome.done(
            "notification_service", delivered=True, priority=priority
        )

    if action == "list":
        return outcome.done("notification_service", **_list_notifications())

    if action == "clear":
        return outcome.done("notification_service", **_clear_notifications())

    return outcome.failed("notification_service", f"unknown action: {action}")


TOOL["handler"] = run_notification_service
