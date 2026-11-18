"""
actions/review_team.py — Team code/document/project review for JARVIS.

Provides structured review capabilities so JARVIS can act as a peer reviewer
for team work: code changes, documentation, project state, security posture,
and HUD design.

Actions:
  list           — list pending review items across code, docs, projects
  review         — review a specific item by name/type
  approve        — approve a review item
  reject         — reject a review item with reason
  status         — report review queue status

Review categories:
  code         — JARVIS actions, plugins, core modules
  docs         — documentation, prompts, README files
  project      — project structure, config, dependencies
  security     — crypto, auth, secrets, network exposure
  hud          — HUD design, colors, task modes, avatar
  social       — social media config, credentials
  studio       — 3D models, engine, avatar mesh

Each review records: reviewer, timestamp, decision, comments.
Decisions are stored in data/reviews/ for audit trail.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from core import outcome
from core.lazyimport import LazyModule, installed

from core import outcome
from core.lazyimport import LazyModule, installed

logger = logging.getLogger(__name__)

_YAML = installed("yaml")
yaml = LazyModule("yaml")

_REVIEW_DIR = Path("reviews")
_CATEGORIES = (
    "code", "docs", "project", "security", "hud", "studio", "social",
)


def _ensure_dir() -> None:
    _REVIEW_DIR.mkdir(parents=True, exist_ok=True)


def _review_path(name: str) -> Path:
    safe = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    return _REVIEW_DIR / f"{safe}.json"


def _load_review(name: str) -> dict | None:
    p = _review_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load review '{p.name}': {e}")
        return None


def _save_review(name: str, data: dict) -> None:
    _ensure_dir()
    _review_path(name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _list_reviews() -> list[dict]:
    _ensure_dir()
    results = []
    for p in sorted(_REVIEW_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["_file"] = p.name
            results.append(data)
        except Exception as e:
            logger.warning(f"Failed to read review file {p.name}: {e}")
            continue
    return results


def _discover_reviewables() -> list[dict]:
    """Discover items that could be reviewed across the project."""
    items = []
    from pathlib import Path as P

    root = P(".")
    # Python files in actions/, plugins/, core/, providers/
    for sub in ("actions", "plugins", "core", "providers"):
        d = root / sub
        if d.is_dir():
            for f in sorted(d.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                items.append({
                    "name": f"{sub}/{f.name}",
                    "type": "code",
                    "path": str(f),
                    "category": "code",
                })
    # Config files
    for f in root.glob("*.json"):
        items.append({
            "name": f.name,
            "type": "config",
            "path": str(f),
            "category": "project",
        })
    for f in root.glob("*.yaml"):
        items.append({
            "name": f.name,
            "type": "config",
            "path": str(f),
            "category": "project",
        })
    for f in root.glob("*.md"):
        items.append({
            "name": f.name,
            "type": "doc",
            "path": str(f),
            "category": "docs",
        })
    return items[:50]  # cap


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "list").strip().lower()

    try:
        if action == "list":
            _ensure_dir()
            reviews = _list_reviews()
            if not reviews:
                return "No review items found. Use 'review' to start a review."
            lines = ["Pending review items:"]
            for r in reviews:
                status = r.get("status", "pending")
                lines.append(f"  {r.get('name', '?')}: {r.get('type', '?')} — {status}")
            return "\n".join(lines)

        if action == "review":
            name = (parameters.get("name") or "").strip()
            rtype = (parameters.get("type") or "code").strip()
            if not name:
                return "Sir, review needs a 'name'."
            r = _load_review(name)
            if r is None:
                # Auto-discover
                found = None
                for item in _discover_reviewables():
                    if item["name"] == name or item["name"].endswith(name):
                        found = item
                        break
                if found is None:
                    return f"Sir, I don't know '{name}'. Use 'list' to see candidates."
                r = {
                    "name": name,
                    "type": found["type"],
                    "category": found.get("category", "code"),
                    "path": found["path"],
                    "status": "pending",
                    "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                _save_review(name, r)
            lines = [f"Review: {r.get('name')}"]
            lines.append(f"  Type: {r.get('type')}")
            lines.append(f"  Category: {r.get('category')}")
            lines.append(f"  Path: {r.get('path', 'N/A')}")
            lines.append(f"  Status: {r.get('status')}")
            if r.get("comments"):
                lines.append(f"  Comments: {r.get('comments')}")
            if r.get("reviewer"):
                lines.append(f"  Reviewer: {r.get('reviewer')}")
            if r.get("reviewed_at"):
                lines.append(f"  Reviewed: {r.get('reviewed_at')}")
            return "\n".join(lines)

        if action == "approve":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, approve needs a 'name'."
            r = _load_review(name)
            if r is None:
                return f"Sir, no review found for '{name}'."
            r["status"] = "approved"
            r["reviewed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            r["reviewer"] = (parameters.get("reviewer") or "jarvis")
            r["comment"] = (parameters.get("comment") or "Approved.")
            _save_review(name, r)
            return f"Approved: {name}"

        if action == "reject":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, reject needs a 'name'."
            comment = (parameters.get("comment") or "No reason given.")
            r = _load_review(name)
            if r is None:
                return f"Sir, no review found for '{name}'."
            r["status"] = "rejected"
            r["reviewed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            r["reviewer"] = (parameters.get("reviewer") or "jarvis")
            r["comment"] = comment
            _save_review(name, r)
            return f"Rejected: {name} — {comment}"

        if action == "status":
            reviews = _list_reviews()
            pending = sum(1 for r in reviews if r.get("status") == "pending")
            approved = sum(1 for r in reviews if r.get("status") == "approved")
            rejected = sum(1 for r in reviews if r.get("status") == "rejected")
            return (f"Review queue: {len(reviews)} total — "
                    f"{pending} pending, {approved} approved, {rejected} rejected")

        if action == "discover":
            items = _discover_reviewables()
            if not items:
                return "No reviewable items found."
            lines = ["Discoverable review items:"]
            for it in items:
                lines.append(f"  {it['name']} [{it['type']}] — {it['path']}")
            return "\n".join(lines)

        return outcome.failed("review_team", f"unknown action: {action}")

    except Exception as exc:
        logger.error(f"Review team error: {exc}", exc_info=True)
        return outcome.failed("review_team", str(exc))


TOOL = {
    "name": "review_team",
    "description": (
        "Team code/document review system for JARVIS. Actions: 'list' (see "
        "pending reviews), 'review' (inspect an item by name), 'approve' "
        "(approve a review), 'reject' (reject with reason), 'status' (queue "
        "summary), 'discover' (find reviewable items). Review categories: "
        "code, docs, project, security, hud, studio, social."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "list | review | approve | reject | status | discover",
            },
            "name": {
                "type": "STRING",
                "description": "Item name to review/approve/reject",
            },
            "type": {
                "type": "STRING",
                "description": "Item type: code | docs | project | security | hud | studio | social",
            },
            "reviewer": {
                "type": "STRING",
                "description": "Reviewer name (default: jarvis)",
            },
            "comment": {
                "type": "STRING",
                "description": "Review comment / reason",
            },
        },
        "required": ["action"],
    },
    "handler": run,
}
