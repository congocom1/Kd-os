"""
actions/kd_assistant.py — Expose the KD awareness/memory/orchestration stack
to the assistant as one tool.

This file is an ordinary action: it is auto-discovered by
core.action_loader, exactly like every other actions/*.py, so nothing in
main.py had to change to make it available. The tool is always DECLARED (the
model must be able to ask), but every operation answers honestly with
"unavailable" when the matching feature flag is off — it never pretends to
have done something it did not do.
"""
from __future__ import annotations

import json


def _runtime():
    from core.kd_runtime import get_kd_runtime
    return get_kd_runtime()


def kd_assistant(operation: str = "status", **kwargs) -> str:
    """Query or drive the real-time assistant subsystems.

    Args:
        operation: One of
            - "status"    : which KD subsystems are active right now
            - "context"   : what the assistant knows right now (state, memory,
                            active task, focused window, known speakers)
            - "recall"    : semantic memory search (needs "query")
            - "remember"  : store a memory (needs "key" and "value")
            - "task"      : queue an autonomous task (needs "goal")
            - "tasks"     : list autonomous tasks / status of one task id
            - "windows"   : list open windows
            - "focus"     : focus a window by id (needs "window_id")
        query: Search text for "recall"
        key:   Memory key for "remember"
        value: Memory value for "remember"
        goal:  Goal text for "task"
        task_id: Task id for "tasks"
        window_id: Window id for "focus"
    """
    op = (operation or "status").strip().lower()
    rt = _runtime()

    try:
        if op == "status":
            return json.dumps(rt.status(), indent=2, default=str)

        if op == "context":
            return json.dumps(rt.snapshot(), indent=2, default=str)

        if op == "recall":
            query = (kwargs.get("query") or "").strip()
            if not query:
                return "Tell me what to search for."
            results = rt.recall(query)
            if not results:
                return f"No memories matched '{query}'."
            lines = [f"• {r.get('matched_text') or r.get('entry')}"
                     for r in results]
            return f"Memories matching '{query}':\n" + "\n".join(lines)

        if op == "remember":
            key = (kwargs.get("key") or "").strip()
            value = (kwargs.get("value") or "").strip()
            if not key or not value:
                return "I need both a key and a value to remember that."
            result = rt.remember(kwargs.get("category") or "notes", key, value)
            if result.get("status") == "stored":
                return f"Remembered '{key}'."
            return f"Could not remember '{key}': {result.get('detail', 'unavailable')}"

        if op == "task":
            goal = (kwargs.get("goal") or "").strip()
            if not goal:
                return "Tell me what the task should be."
            result = rt.submit_task(goal, kwargs.get("priority") or "normal")
            if result.get("status") == "queued":
                task = result.get("task") or {}
                return (f"Task queued ({task.get('id')}): {goal}\n"
                        f"Steps: {len(task.get('steps') or [])}")
            return f"Could not queue that task: {result.get('detail', result.get('status'))}"

        if op == "tasks":
            result = rt.task_status(kwargs.get("task_id"))
            if result.get("status") != "ok":
                return f"Task status unavailable: {result.get('status')}"
            if kwargs.get("task_id"):
                task = result.get("task")
                if not task:
                    return "No task with that id."
                return (f"Task {task['id']}: {task['name']} — "
                        f"{task['status']} ({int(task.get('progress', 0) * 100)}%)")
            tasks = result.get("tasks") or []
            if not tasks:
                return "No tasks yet."
            return "\n".join(
                f"• {t['id']} — {t['name']} ({t['status']}, "
                f"{int(t.get('progress', 0) * 100)}%)" for t in tasks)

        if op == "windows":
            windows = rt.list_windows()
            if not windows:
                return "No windows are visible to me right now."
            lines = [f"• {w.get('window_id')} — {w.get('title')} [{w.get('app_name')}]"
                     for w in windows]
            return "Open windows:\n" + "\n".join(lines)

        if op == "focus":
            window_id = (kwargs.get("window_id") or "").strip()
            if not window_id:
                return "Which window should I focus? Give me its id."
            result = rt.focus_window(window_id)
            if result.get("status") == "done":
                return f"Focused window {window_id}."
            return f"Could not focus window {window_id}: {result.get('status')}"

        return (f"Unknown operation '{op}'. Use one of: status, context, recall, "
                "remember, task, tasks, windows, focus.")
    except Exception as e:
        # A tool must never take the session down.
        return f"The assistant's real-time subsystems are unavailable right now ({e})."


TOOL = {
    "name": "kd_assistant",
    "description": (
        "Interact with the assistant's real-time awareness layer: check which "
        "subsystems are active, read the live context (current state, memory, "
        "active task, focused window, known speakers), search or store memories, "
        "queue or inspect autonomous tasks, and list or focus open windows. "
        "Use 'status' to see what is actually available before promising the "
        "user anything."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {
                "type": "STRING",
                "enum": ["status", "context", "recall", "remember", "task",
                         "tasks", "windows", "focus"],
                "description": "Which operation to perform.",
            },
            "query": {"type": "STRING", "description": "Search text for 'recall'."},
            "key": {"type": "STRING", "description": "Memory key for 'remember'."},
            "value": {"type": "STRING", "description": "Memory value for 'remember'."},
            "category": {"type": "STRING",
                         "description": "Memory category for 'remember'."},
            "goal": {"type": "STRING",
                     "description": "Goal text for 'task'."},
            "priority": {"type": "STRING",
                         "description": "low | normal | high | critical for 'task'."},
            "task_id": {"type": "STRING", "description": "Task id for 'tasks'."},
            "window_id": {"type": "STRING", "description": "Window id for 'focus'."},
        },
        "required": ["operation"],
    },
    "handler": kd_assistant,
}
