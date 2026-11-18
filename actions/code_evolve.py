"""
code_evolve — safe, human-gated code modification for JARVIS.

Propose, review, and apply code changes. Every apply is a git commit, so
every change is reversible. Nothing is ever modified automatically.

Actions:
  propose     — propose a change: name, target_file, new_body, reason
  review      — show the diff for a proposal
  list        — list all pending proposals
  apply       — apply a proposal (git backup + write + commit)
  delete      — delete a proposal without applying

"""

from __future__ import annotations

from core.code_evolution import propose, review, list_proposals, apply, delete

PLUGIN = {
    "name": "code_evolve",
    "description": (
        "Safely modify JARVIS's own code. propose() saves a change for review "
        "(does NOT touch source). review() shows the diff. apply() backs up the "
        "file to git, writes the change, and commits. delete() removes a "
        "proposal. Every applied change is a git commit and is reversible. "
        "Nothing happens automatically."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'propose', 'review', 'list', 'apply', 'delete'",
            },
            "name": {
                "type": "STRING",
                "description": "Proposal name (for propose/review/apply/delete)",
            },
            "target_file": {
                "type": "STRING",
                "description": "File to modify (for propose), relative to project root",
            },
            "new_body": {
                "type": "STRING",
                "description": "Complete new file content (for propose)",
            },
            "reason": {
                "type": "STRING",
                "description": "Why this change is being proposed (for propose)",
            },
        },
        "required": ["action"],
    },
}

# This is an action (TOOL dict), not a plugin. It follows the action_loader
# convention with a module-level TOOL and a run() handler.

TOOL = {
    "name": "code_evolve",
    "description": PLUGIN["description"],
    "parameters": PLUGIN["parameters"],
    "handler": None,  # set below
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()
    if not action:
        return "Sir, please specify: propose, review, list, apply, or delete."

    try:
        if action == "propose":
            name = (parameters.get("name") or "").strip()
            target_file = (parameters.get("target_file") or "").strip()
            new_body = parameters.get("new_body") or ""
            reason = (parameters.get("reason") or "").strip()
            if not name or not target_file:
                return "Sir, propose needs both 'name' and 'target_file'."
            return propose(name, target_file, new_body, reason)

        if action == "review":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, review needs a 'name'."
            return review(name)

        if action == "list":
            return list_proposals()

        if action == "apply":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, apply needs a 'name'."
            return apply(name)

        if action == "delete":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, delete needs a 'name'."
            return delete(name)

        return f"Sir, I don't recognize the action '{action}'."

    except Exception as e:
        return f"Sir, code_evolve failed: {e}"


TOOL["handler"] = run
