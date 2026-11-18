"""
actions/skills.py — Invoke and manage SKILL.md skills for JARVIS.

Skills are markdown instruction files (SKILL.md) sourced from community
repositories such as https://github.com/taoufik123-collab/jarvis-skills.git.
They are NOT executable code — they are agent instructions that, when active,
are prepended to the Live session's system instruction so the model adopts
that persona and workflow.

Actions:
  list         — list all discovered skills with name and description
  activate     — activate a skill by name (needs 'name')
  deactivate   — clear the currently active skill
  status       — report the currently active skill, if any

When a skill is active, its SKILL.md content is injected into the system
instruction for every subsequent Live session turn until deactivated.
"""

from __future__ import annotations

from core.skills_loader import discover_all_skills
from core.lazyimport import LazyModule, installed

_YAML = installed("yaml")
yaml = LazyModule("yaml")

_BASE_DIR = None  # set on first use


def _base_dir():
    global _BASE_DIR
    if _BASE_DIR is None:
        import sys
        from pathlib import Path

        if getattr(sys, "frozen", False):
            _BASE_DIR = Path(sys.executable).parent
        else:
            _BASE_DIR = Path(__file__).resolve().parent.parent
    return _BASE_DIR


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "list").strip().lower()

    try:
        if action == "list":
            skills = discover_all_skills(_base_dir())
            if not skills:
                return "No skills discovered. Clone a skills repo into skills/vendor/."
            lines = ["Sir, available knowledge domains:"]
            for name in sorted(skills):
                rec = skills[name]
                origin = f" [{rec.source}]" if rec.source else ""
                lines.append(f"• {name}{origin} — {rec.description}")
            lines.append(
                "\nSay 'activate skill <name>' to load one, or 'deactivate skill' to clear."
            )
            return "\n".join(lines)

        if action == "activate":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, please specify a skill name to activate."
            skills = discover_all_skills(_base_dir())
            if name not in skills:
                available = ", ".join(sorted(skills.keys())) or "none"
                return f"Sir, skill '{name}' not found. Available: {available}"
            if player:
                try:
                    player._active_skill = name
                except Exception:
                    pass
            rec = skills[name]
            return (
                f"Sir, skill '{name}' activated — {rec.description}. "
                f"I'm now operating as that skill. Say what you'd like to do."
            )

        if action == "deactivate":
            if player:
                try:
                    player._active_skill = None
                except Exception:
                    pass
            return "Sir, skill deactivated. Back to standard JARVIS mode."

        if action == "status":
            active = getattr(player, "_active_skill", None) if player else None
            if active:
                skills = discover_all_skills(_base_dir())
                rec = skills.get(active)
                desc = rec.description if rec else "(description unavailable)"
                return f"Sir, active skill: {active} — {desc}."
            return "Sir, no skill is active. Say 'list skills' to see what's available."

        return f"Sir, I don't recognize the skills action '{action}'."

    except Exception as exc:
        return f"Sir, skills action failed: {exc}"


TOOL = {
    "name": "skills",
    "description": (
        "Manage JARVIS skills — markdown agent instructions from community "
        "repositories. Actions: 'list' (see available skills), 'activate' "
        "(needs 'name' to load a skill), 'deactivate' (clear active skill), "
        "status (show current skill). When a skill is active, its instructions "
        "shape JARVIS's behavior for the rest of the session."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "list | activate | deactivate | status",
            },
            "name": {
                "type": "STRING",
                "description": "Skill name to activate (for action='activate')",
            },
        },
        "required": ["action"],
    },
    "handler": run,
}
