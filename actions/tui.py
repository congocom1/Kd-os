"""
actions/tui.py — Curses-based terminal UI for JARVIS.

Provides a lightweight terminal interface using Python's curses library,
allowing JARVIS to run without PyQt6/X11. Useful for SSH sessions, headless
servers, or when a graphical display is unavailable.

Actions:
  tui        — launch the curses terminal UI (needs no parameters)

Keys in the TUI:
    Enter        send query
    Ctrl-C       quit
    Ctrl-L       clear transcript

The TUI connects to Mark-LVI's action/plugin system directly, so any registered
action or plugin can be invoked from the terminal.
"""

from __future__ import annotations

import curses
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

from core.action_loader import discover_actions
from core.plugin_loader import discover_plugins

_MAX_TRANSCRIPT_LINES = 500


class Transcript:
    """Bounded, wrap-aware scrollback buffer."""

    def __init__(self, width: int = 80, limit: int = _MAX_TRANSCRIPT_LINES):
        self.lines: Deque[str] = deque(maxlen=limit)
        self.width = width

    def resize(self, width: int) -> None:
        if width != self.width:
            self.width = width
            self.lines.clear()

    def add(self, text: str, role: str = "system", prefix: str = "") -> None:
        for raw in str(text).splitlines() or [""]:
            wrapped = self._wrap(prefix + raw)
            self.lines.extend(wrapped)

    def _wrap(self, line: str) -> List[str]:
        w = max(self.width - 2, 8)
        if len(line) <= w:
            return [line]
        out = []
        while line:
            out.append(line[:w])
            line = line[w:]
        return out

    def render(self, height: int) -> List[str]:
        if height <= 0:
            return []
        return list(self.lines)[-height:]


def _build_action_map() -> dict:
    """Build a flat map of action name -> (registry_type, record)."""
    actions = discover_actions(Path("actions"), set())
    plugins = discover_plugins(Path("plugins"), set())

    amap: dict = {}
    for name in actions.names():
        rec = actions._actions[name]
        amap[name] = ("action", rec)

    for name in plugins._plugins:
        rec = plugins._plugins[name]
        amap[name] = ("plugin", rec)

    return amap


def _run_action(amap: dict, name: str, parameters: dict) -> str:
    """Run an action or plugin by name with the given parameters."""
    if name not in amap:
        return f"Unknown action or plugin: '{name}'"

    rtype, rec = amap[name]

    try:
        if rtype == "action":
            handler = rec.handler
            result = handler(parameters)
            return result or "Done."

        else:  # plugin
            result = rec.run(parameters)
            return result or "Done."

    except Exception as exc:
        return f"Error running '{name}': {exc}"


def _curses_main(stdscr) -> None:
    """Main curses loop."""
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    # Try to use colors
    try:
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)    # system
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)   # user
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # result
        curses.init_pair(4, curses.COLOR_MAGENTA, curses.COLOR_BLACK) # error
        colors_ok = True
    except Exception:
        colors_ok = False

    transcript = Transcript()
    input_buf = ""
    cursor_pos = 0
    running = True
    busy = False

    # Build action map once at startup
    try:
        amap = _build_action_map()
    except Exception as exc:
        amap = {}
        transcript.add(f"Failed to load actions: {exc}", role="error")

    transcript.add("JARVIS TUI online. Type a query and press Enter.", role="system")
    transcript.add("Available commands: list actions, list plugins, run <name> <args>", role="system")
    transcript.add("Press Ctrl-C to quit.", role="system")

    while running:
        # Render
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        transcript.resize(w)

        # Header
        header = " JARVIS Terminal UI "
        stdscr.addnstr(0, 0, header, w - 1, curses.A_BOLD)

        # Transcript area
        t_start = 2
        t_end = h - 3
        rendered = transcript.render(t_end - t_start)
        for i, line in enumerate(rendered):
            if t_start + i >= h - 2:
                break
            # Color based on role prefix
            if line.startswith("> "):
                attr = curses.color_pair(2) if colors_ok else 0
            elif line.startswith(("Error", "error", "Error:")):
                attr = curses.color_pair(4) if colors_ok else 0
            else:
                attr = curses.color_pair(1) if colors_ok else 0
            stdscr.addnstr(t_start + i, 0, line, w - 1, attr)

        # Input line
        input_line = h - 2
        prompt = "> "
        display = prompt + input_buf
        stdscr.addnstr(input_line, 0, display, w - 1)
        try:
            stdscr.move(input_line, len(prompt) + cursor_pos)
        except Exception:
            pass

        # Status line
        status = f"Actions: {len(amap)} | Busy: {busy}"
        stdscr.addnstr(h - 1, 0, status, w - 1, curses.A_DIM)

        stdscr.refresh()

        # Input
        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            break

        if key == -1:
            continue

        if key == curses.KEY_RESIZE:
            transcript.resize(w)
            continue

        if key in (curses.KEY_ENTER, 10, 13):  # Enter
            query = input_buf.strip()
            input_buf = ""
            cursor_pos = 0

            if not query:
                continue

            transcript.add(query, role="user", prefix="> ")

            # Handle special commands
            if query.lower() in ("quit", "exit", "q"):
                running = False
                continue
            if query.lower() in ("clear", "cls"):
                transcript.lines.clear()
                continue
            if query.lower() in ("list actions", "actions"):
                names = sorted(amap.keys())
                transcript.add("Available actions:" + (" " + ", ".join(names) if names else " none"), role="system")
                continue
            if query.lower() in ("list plugins", "plugins"):
                from core.plugin_loader import discover_plugins
                plugins = discover_plugins(Path("plugins"), set())
                names = sorted(plugins._plugins.keys())
                transcript.add("Available plugins:" + (" " + ", ".join(names) if names else " none"), role="system")
                continue

            # Parse "run <name> <args>" or just treat as a query
            parts = query.split(None, 1)
            if parts[0].lower() == "run" and len(parts) > 1:
                # run <name> <key=value key2=value2 ...>
                run_parts = parts[1].split(None, 1)
                action_name = run_parts[0]
                params = {}
                if len(run_parts) > 1:
                    for kv in run_parts[1].split():
                        if "=" in kv:
                            k, v = kv.split("=", 1)
                            params[k] = v
                busy = True
                try:
                    result = _run_action(amap, action_name, params)
                    transcript.add(result, role="result", prefix="➜ ")
                except Exception as exc:
                    transcript.add(f"Error: {exc}", role="error")
                busy = False
            else:
                # Treat as a natural language query - try to match an action
                # First try exact action name match
                if query in amap:
                    busy = True
                    try:
                        result = _run_action(amap, query, {})
                        transcript.add(result, role="result", prefix="➜ ")
                    except Exception as exc:
                        transcript.add(f"Error: {exc}", role="error")
                    busy = False
                else:
                    transcript.add(
                        "No matching action. Use 'run <name> key=value ...' or type 'list actions'.",
                        role="system",
                    )

        elif key in (curses.KEY_BACKSPACE, 127, 8):  # Backspace
            if cursor_pos > 0:
                input_buf = input_buf[: cursor_pos - 1] + input_buf[cursor_pos:]
                cursor_pos -= 1

        elif key == curses.KEY_DC:  # Delete
            if cursor_pos < len(input_buf):
                input_buf = input_buf[:cursor_pos] + input_buf[cursor_pos + 1 :]

        elif key == curses.KEY_LEFT:
            if cursor_pos > 0:
                cursor_pos -= 1

        elif key == curses.KEY_RIGHT:
            if cursor_pos < len(input_buf):
                cursor_pos += 1

        elif key == curses.KEY_HOME:
            cursor_pos = 0

        elif key == curses.KEY_END:
            cursor_pos = len(input_buf)

        elif key == curses.KEY_UP:
            # Scroll transcript up (not implemented simply)
            pass

        elif key == curses.KEY_DOWN:
            pass

        elif 32 <= key <= 126:  # Printable characters
            input_buf = input_buf[:cursor_pos] + chr(key) + input_buf[cursor_pos:]
            cursor_pos += 1


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Launch the TUI interface."""
    try:
        curses.wrapper(_curses_main)
        return "TUI session ended."
    except Exception as exc:
        return f"TUI failed to start: {exc}"


TOOL = {
    "name": "tui",
    "description": (
        "Launch a curses-based terminal UI for JARVIS. Lightweight alternative "
        "to the PyQt6 HUD, works over SSH and on headless servers. Type "
        "'list actions' to see available actions, 'run <name> key=value ...' to "
        "execute an action, or Ctrl-C to quit."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
    "handler": run,
}
