"""
plugins/sqlite_commands.py — SQLite command database plugin for JARVIS.

Stores command-to-app/URL mappings in a SQLite database, allowing users to
define custom commands that open applications or web pages. Inspired by the
Sophia-AI-Assistant engine pattern (engine/db.py, engine/features.py).

Actions:
  cmd_add       — add a command mapping (needs 'name', 'type', 'target')
  cmd_remove    — remove a command mapping (needs 'name')
  cmd_list      — list all command mappings
  cmd_run       — run a mapped command (needs 'name')
  cmd_import    — import from Sophia-AI style database (needs 'db_path')

Command types:
  app     — local application path (opened via open_app)
  url     — web URL (opened via web_search or open_app)
  shell   — shell command (executed directly)

The database is stored at data/sqlite_commands.db by default.
"""

from __future__ import annotations
from core.metrics import increment, record_timing
import functools

import os
import sqlite3
import subprocess
from pathlib import Path

_DB_PATH = Path("data") / "sqlite_commands.db"


@functools.lru_cache(maxsize=1)
def _ensure_db() -> sqlite3.Connection:
    """Ensure the database and table exist, return a cached connection.

    The connection is cached for the lifetime of the process, so callers
    must NOT close it — use :func:`_close_db` to release it explicitly.
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) UNIQUE NOT NULL,
            ctype VARCHAR(20) NOT NULL,
            target VARCHAR(1000) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.commit()
    return conn


def _close_db() -> None:
    """Close and evict the cached database connection."""
    try:
        conn = _ensure_db()
    except Exception:
        return
    try:
        conn.close()
    except Exception:
        pass
    _ensure_db.cache_clear()


def _cmd_add(conn: sqlite3.Connection, name: str, ctype: str, target: str) -> str:
    name = name.strip().lower()
    ctype = ctype.strip().lower()
    target = target.strip()

    if ctype not in ("app", "url", "shell"):
        return "Invalid type. Must be: app, url, or shell."

    try:
        conn.execute(
            "INSERT OR REPLACE INTO commands (name, ctype, target) VALUES (?, ?, ?)",
            (name, ctype, target),
        )
        conn.commit()
        return f"Command '{name}' ({ctype}: {target}) saved."
    except Exception as exc:
        return f"Failed to save command: {exc}"


def _cmd_remove(conn: sqlite3.Connection, name: str) -> str:
    name = name.strip().lower()
    cur = conn.execute("DELETE FROM commands WHERE name = ?", (name,))
    conn.commit()
    if cur.rowcount > 0:
        return f"Command '{name}' removed."
    return f"Command '{name}' not found."


def _cmd_list(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT name, ctype, target FROM commands ORDER BY name"
    ).fetchall()
    if not rows:
        return "No commands defined."
    lines = ["Defined commands:"]
    for name, ctype, target in rows:
        lines.append(f"  {name} [{ctype}]: {target}")
    return "\n".join(lines)


def _cmd_run(conn: sqlite3.Connection, name: str) -> str:
    name = name.strip().lower()
    row = conn.execute(
        "SELECT ctype, target FROM commands WHERE name = ?", (name,)
    ).fetchone()
    if not row:
        return f"Command '{name}' not found."

    ctype, target = row

    if ctype == "app":
        # Use the open_app action
        from actions.open_app import open_app as _open_app

        result = _open_app({"app_name": target})
        return result or f"Opened '{name}' ({target})."

    elif ctype == "url":
        # Open URL via web_search or directly
        import webbrowser

        try:
            webbrowser.open(target)
            return f"Opened '{name}' ({target}) in browser."
        except Exception as exc:
            return f"Failed to open URL: {exc}"

    elif ctype == "shell":
        try:
            subprocess.Popen(target, shell=True)
            return f"Executed '{name}' ({target})."
        except Exception as exc:
            return f"Failed to execute shell command: {exc}"

    return f"Unknown command type: {ctype}"


def _cmd_import(conn: sqlite3.Connection, db_path: str) -> str:
    """Import commands from a Sophia-AI style sophia.db database."""
    if not os.path.isfile(db_path):
        return f"Database file not found: {db_path}"

    try:
        src = sqlite3.connect(db_path)
        # Try sys_command table (app paths)
        try:
            rows = src.execute(
                "SELECT name, path FROM sys_command"
            ).fetchall()
            for name, path in rows:
                conn.execute(
                    "INSERT OR REPLACE INTO commands (name, ctype, target) VALUES (?, ?, ?)",
                    (name, "app", path),
                )
        except sqlite3.OperationalError:
            pass

        # Try web_command table (URLs)
        try:
            rows = src.execute(
                "SELECT name, url FROM web_command"
            ).fetchall()
            for name, url in rows:
                conn.execute(
                    "INSERT OR REPLACE INTO commands (name, ctype, target) VALUES (?, ?, ?)",
                    (name, "url", url),
                )
        except sqlite3.OperationalError:
            pass

        conn.commit()
        src.close()
        return "Import complete."
    except Exception as exc:
        return f"Import failed: {exc}"


PLUGIN = {
    "name": "sqlite_commands",
    "description": (
        "SQLite command database for JARVIS. Stores command-to-app/URL mappings "
        "in a local SQLite database. Inspired by Sophia-AI-Assistant's engine. "
        "Actions: cmd_add, cmd_remove, cmd_list, cmd_run, cmd_import. "
        "Command types: app (local application), url (web URL), shell (shell command)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'cmd_add', 'cmd_remove', 'cmd_list', 'cmd_run', 'cmd_import'",
            },
            "name": {
                "type": "STRING",
                "description": "Command name (for cmd_add, cmd_remove, cmd_run)",
            },
            "ctype": {
                "type": "STRING",
                "description": "Command type: 'app', 'url', or 'shell' (for cmd_add)",
            },
            "target": {
                "type": "STRING",
                "description": "Target path/URL/command (for cmd_add)",
            },
            "db_path": {
                "type": "STRING",
                "description": "Path to Sophia-AI sophia.db to import from (for cmd_import)",
            },
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Run a SQLite database operation.

    Supports adding, querying, and managing SQLite database records.

    Parameters:
        parameters: Dict with "action" and the parameters that action needs.

    Returns:
        Query result or status message.
    """
    increment("sqlite_commands.operation")
    action = (parameters.get("action") or "").strip().lower()
    if not action:
        return "Sir, please specify an action: cmd_add, cmd_remove, cmd_list, cmd_run, cmd_import."

    try:
        conn = _ensure_db()

        if action == "cmd_add":
            name = parameters.get("name", "").strip()
            ctype = parameters.get("ctype", "").strip()
            target = parameters.get("target", "").strip()
            if not name or not ctype or not target:
                return "Sir, cmd_add needs 'name', 'ctype', and 'target'."
            result = _cmd_add(conn, name, ctype, target)

        elif action == "cmd_remove":
            name = parameters.get("name", "").strip()
            if not name:
                return "Sir, cmd_remove needs a 'name'."
            result = _cmd_remove(conn, name)

        elif action == "cmd_list":
            result = _cmd_list(conn)

        elif action == "cmd_run":
            name = parameters.get("name", "").strip()
            if not name:
                return "Sir, cmd_run needs a 'name'."
            result = _cmd_run(conn, name)

        elif action == "cmd_import":
            db_path = parameters.get("db_path", "").strip()
            if not db_path:
                return "Sir, cmd_import needs a 'db_path'."
            result = _cmd_import(conn, db_path)

        else:
            return f"Sir, I don't recognize the action '{action}'."

        return result

    except Exception as exc:
        return f"Sir, sqlite_commands failed: {exc}"


def _list_action(values: dict) -> tuple[bool, str]:
    try:
        conn = _ensure_db()
        return True, _cmd_list(conn)
    except Exception as exc:
        return False, str(exc)


# ── Plugin settings (shown in ⚙ → PLUGINS → sqlite_commands) ───────────────
PLUGIN_SETTINGS = {
    "namespace": "sqlite_commands",
    "title": "SQLite Commands",
    "fields": [
        {
            "key": "db_path",
            "label": "Database file path",
            "type": "text",
            "default": "data/sqlite_commands.db",
            "placeholder": "data/sqlite_commands.db",
        },
    ],
    "action": {
        "label": "LIST COMMANDS",
        "run": _list_action,
    },
}
