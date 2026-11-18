"""
Personal Notes skill — save and recall notes in JARVIS long-term memory.

Integrates with memory/memory_manager.py so notes persist across sessions.
Auto-discovered by core/plugin_loader at startup.
"""

from memory.memory_manager import (
    update_memory,
    search_memory,
    all_entries_for_ui,
)

PLUGIN = {
    "name": "personal_notes",
    "description": (
        "Save, recall, or list personal notes in JARVIS long-term memory. "
        "Use 'save' to remember something, 'recall' to find a note by keyword, "
        "or 'list' to see all stored notes. Notes survive between sessions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'save', 'recall', or 'list'",
            },
            "key": {
                "type": "STRING",
                "description": "A short name/title for the note (used when saving or recalling)",
            },
            "value": {
                "type": "STRING",
                "description": "The note content to save",
            },
            "keyword": {
                "type": "STRING",
                "description": "A word to search for when recalling notes",
            },
        },
        "required": ["action"],
    },
}

def _count_notes(values: dict) -> tuple[bool, str]:
    """Count how many notes are stored."""
    try:
        rows = all_entries_for_ui()
        return True, f"{len(rows)} notes stored."
    except Exception as e:
        return False, f"Error: {e}"


# ── Plugin settings (shown in ⚙ → PLUGINS → personal_notes) ───────────────
PLUGIN_SETTINGS = {
    "namespace": "personal_notes",
    "title": "Personal Notes",
    "fields": [
        {
            "key": "default_category",
            "label": "Default note category",
            "type": "text",
            "default": "general",
            "placeholder": "general",
        },
    ],
    "action": {
        "label": "COUNT NOTES",
        "run": _count_notes,
    },
}


_VALID_ACTIONS = {"save", "recall", "list"}


def _format_note_rows(rows: list[dict]) -> str:
    """Format memory entries for the spoken list response."""
    lines = [f"• {r['category']}/{r['key']}: {r['value'][:60]}" for r in rows[:20]]
    return "Here are your stored notes:\n" + "\n".join(lines)


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()
    if action not in _VALID_ACTIONS:
        return "Sir, I need an action: save, recall, or list."

    if action == "list":
        try:
            rows = all_entries_for_ui()
        except Exception:
            rows = []
        if not rows:
            return "Your memory is empty, sir."
        return _format_note_rows(rows)

    if action == "save":
        key = (parameters.get("key") or "").strip()
        value = (parameters.get("value") or "").strip()
        if not key or not value:
            return "Sir, please provide both a key (title) and the note content."
        try:
            update_memory({"notes": {key: {"value": value}}})
        except Exception as e:
            return f"Sir, I couldn't save that note: {e}"
        if player:
            try:
                player.write_log(f"JARVIS: Note saved — {key}")
            except Exception:
                pass
        return f"Note saved: {key} = {value}"

    # recall — search_memory returns a formatted string
    keyword = (parameters.get("keyword") or parameters.get("key") or "").strip()
    if not keyword:
        return "Sir, please give me a keyword or note title to recall."
    try:
        return search_memory(keyword, limit=10)
    except Exception as e:
        return f"Sir, I couldn't search your notes: {e}"
