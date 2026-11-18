"""
actions/clipboard.py — System clipboard read/write for JARVIS.

Uses pyperclip (already installed) to read from and write to the OS clipboard.
Safe by design: reading returns the content, writing only happens on explicit
request, and nothing is ever exfiltrated — the clipboard stays on this machine.

Actions:
  read   — return the current clipboard text
  write  — store text to the clipboard (needs 'text')
  clear  — empty the clipboard
"""

from __future__ import annotations

from core import outcome
from core.lazyimport import LazyModule, installed

_PYPERCLIP = installed("pyperclip")
pyperclip = LazyModule("pyperclip")


def _clipboard_read() -> str:
    if not _PYPERCLIP:
        raise RuntimeError("pyperclip is not installed — pip install pyperclip")
    return pyperclip.paste() or ""


def _clipboard_write(text: str) -> None:
    if not _PYPERCLIP:
        raise RuntimeError("pyperclip is not installed — pip install pyperclip")
    pyperclip.copy(text)


def _clipboard_clear() -> None:
    if not _PYPERCLIP:
        raise RuntimeError("pyperclip is not installed — pip install pyperclip")
    pyperclip.copy("")


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "read").strip().lower()

    try:
        if action == "read":
            text = _clipboard_read()
            if not text:
                return outcome.done("clipboard", content="", empty=True)
            if player:
                try:
                    player.write_log(f"[Clipboard] read {len(text)} chars")
                except Exception:
                    pass
            return outcome.done("clipboard", content=text, empty=False)

        if action == "write":
            text = parameters.get("text", "")
            if text is None:
                return outcome.failed("clipboard", "write needs a 'text' value")
            _clipboard_write(str(text))
            if player:
                try:
                    player.write_log(f"[Clipboard] wrote {len(str(text))} chars")
                except Exception:
                    pass
            return outcome.done("clipboard", written=len(str(text)))

        if action == "clear":
            _clipboard_clear()
            return outcome.done("clipboard", cleared=True)

        return outcome.failed("clipboard", f"unknown action: {action}")

    except Exception as e:
        return outcome.failed("clipboard", str(e))


TOOL = {
    "name": "clipboard",
    "description": (
        "Read from or write to the system clipboard. Actions: 'read' (get "
        "current clipboard text), 'write' (needs 'text' to store), 'clear' "
        "(empty the clipboard). Everything stays on this machine — nothing "
        "leaves the clipboard."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "read | write | clear",
            },
            "text": {
                "type": "STRING",
                "description": "Text to write to the clipboard (action='write')",
            },
        },
        "required": ["action"],
    },
    "handler": run,
}
