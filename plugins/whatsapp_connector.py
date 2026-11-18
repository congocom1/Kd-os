"""
plugins/whatsapp_connector.py — WhatsApp connector for JARVIS.

Sends WhatsApp messages through desktop automation using PyAutoGUI (the same
approach as the built-in send_message action). This opens WhatsApp Desktop,
searches for a contact, and types the message — no API key or phone number
registration required.

Actions:
  send      — send a message to a contact (needs 'contact', 'message')
  status    — report whether WhatsApp automation is available

Settings (⚙ → PLUGINS → whatsapp_connector):
  app_name   — the WhatsApp application name (default: WhatsApp)
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import time

from core.lazyimport import LazyModule, installed
from memory.config_manager import get_plugin_config

_PYAUTOGUI = installed("pyautogui")
_PYPERCLIP = installed("pyperclip")

pyautogui = LazyModule("pyautogui")
pyperclip = LazyModule("pyperclip")

_SEARCH_SETTLE = 1.0
_TYPE_SETTLE = 0.6


def _configure_pyautogui(module) -> None:
    module.FAILSAFE = True
    module.PAUSE = 0.06


def _get_app_name(values: dict) -> str:
    return values.get("app_name", "WhatsApp").strip() or "WhatsApp"


def _require_pyautogui() -> None:
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _paste_text(text: str) -> None:
    _require_pyautogui()
    import platform as _platform

    os_name = _platform.system().lower()
    paste_hotkey = ("command", "v") if os_name == "darwin" else ("ctrl", "v")
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey(*paste_hotkey)
        time.sleep(0.1)
    else:
        pyautogui.write(text, interval=0.03)


def _open_whatsapp(app_name: str) -> bool:
    _require_pyautogui()
    import platform as _platform

    os_name = _platform.system().lower()
    try:
        if os_name == "windows":
            pyautogui.press("win")
            time.sleep(0.5)
            _paste_text(app_name)
            time.sleep(_SEARCH_SETTLE)
            pyautogui.press("enter")
            time.sleep(_TYPE_SETTLE)
            return True
        elif os_name == "darwin":
            pyautogui.hotkey("command", "space")
            time.sleep(0.5)
            _paste_text(app_name)
            time.sleep(_SEARCH_SETTLE)
            pyautogui.press("enter")
            time.sleep(_TYPE_SETTLE)
            return True
        else:
            for launcher in (
                ["gtk-launch", app_name.lower()],
                [app_name.lower()],
            ):
                try:
                    import subprocess as _subprocess

                    _subprocess.Popen(
                        launcher,
                        stdout=_subprocess.DEVNULL,
                        stderr=_subprocess.DEVNULL,
                    )
                    time.sleep(_TYPE_SETTLE)
                    return True
                except FileNotFoundError:
                    continue
            return False
    except Exception as exc:
        print(f"[WhatsApp] open failed: {exc}")
        return False


def _search_contact(contact: str) -> bool:
    _require_pyautogui()
    try:
        time.sleep(1.0)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.3)
        _paste_text(contact)
        time.sleep(_SEARCH_SETTLE)
        pyautogui.press("enter")
        time.sleep(0.5)
        return True
    except Exception as exc:
        print(f"[WhatsApp] search failed: {exc}")
        return False


def _type_message(message: str) -> bool:
    _require_pyautogui()
    try:
        _paste_text(message)
        time.sleep(0.3)
        pyautogui.press("enter")
        time.sleep(0.5)
        return True
    except Exception as exc:
        print(f"[WhatsApp] type failed: {exc}")
        return False


def _send(values: dict, parameters: dict) -> str:
    contact = (parameters.get("contact") or "").strip()
    message = (parameters.get("message") or "").strip()
    if not contact:
        return "Sir, I need a contact name to send a WhatsApp message."
    if not message:
        return "Sir, I need a message to send."
    try:
        app_name = _get_app_name(values)
        if not _open_whatsapp(app_name):
            return (
                f"Sir, I could not open WhatsApp ({app_name}). Make sure it is "
                "installed and try again."
            )
        if not _search_contact(contact):
            return f"Sir, I could not find the contact '{contact}' in WhatsApp."
        if not _type_message(message):
            return "Sir, I could not type the message."
        return f"Sir, message sent to {contact} on WhatsApp."
    except Exception as exc:
        return f"Sir, WhatsApp send failed: {exc}"


def _status(values: dict) -> str:
    if not _PYAUTOGUI:
        return "Sir, WhatsApp automation is not available — PyAutoGUI is not installed."
    app_name = _get_app_name(values)
    return (
        f"Sir, WhatsApp connector is ready. App name: {app_name}. "
        "Say 'send whatsapp to <contact> message <text>' to send a message."
    )


PLUGIN = {
    "name": "whatsapp_connector",
    "description": (
        "Send WhatsApp messages through desktop automation. Opens WhatsApp "
        "Desktop, searches for a contact, and types your message — no API key "
        "or phone registration needed. Use 'send' with 'contact' and 'message'. "
        "Works on Windows, macOS, and Linux."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'send' or 'status'",
            },
            "contact": {
                "type": "STRING",
                "description": "Contact name in WhatsApp (for send)",
            },
            "message": {
                "type": "STRING",
                "description": "Message text to send (for send)",
            },
        },
        "required": ["action"],
    },
}

# ── Plugin settings (shown in ⚙ → PLUGINS → whatsapp_connector) ─────────────
PLUGIN_SETTINGS = {
    "namespace": "whatsapp_connector",
    "title": "WhatsApp Connector",
    "fields": [
        {
            "key": "app_name",
            "label": "WhatsApp application name",
            "type": "text",
            "default": "WhatsApp",
            "placeholder": "WhatsApp",
        },
    ],
    "action": {
        "label": "STATUS",
        "run": _status,
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Run WhatsApp automation.

    Supports sending messages, searching contacts, and typing messages on WhatsApp.

    Parameters:
        parameters: Dict with action and required parameters.

    Returns:
        Status message or result.
    """
    action = (parameters.get("action") or "send").strip().lower()
    values = get_plugin_config("whatsapp_connector")
    try:
        if action == "send":
            return _send(values, parameters)
        if action == "status":
            return _status(values)
        return f"Sir, I don't recognize the WhatsApp action '{action}'."
    except Exception as exc:
        return f"Sir, whatsapp_connector failed: {exc}"
