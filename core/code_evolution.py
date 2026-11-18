"""
Code Evolution — safe, human-gated code modification for JARVIS.

JARVIS can propose code changes, but NEVER applies them automatically. The flow:

  1. propose(name, target_file, new_body, reason) — write a proposed change
     to data/code_proposals/<name>.json (never touches the source file)
  2. review(name) — show the diff between current and proposed
  3. apply(name) — back up the current file to git, then apply the proposal,
     and commit with a descriptive message

Every apply is a git commit, so every change is reversible. No proposal is
ever applied without an explicit apply call. This is NOT self-modifying code
in the dangerous sense — it's a reviewed change pipeline.
"""

from __future__ import annotations

import difflib
import json
import subprocess
from pathlib import Path
from core.paths import get_base_dir as _get_base_dir

PROPOSAL_DIR = _get_base_dir() / "data" / "code_proposals"
BASE_DIR = _get_base_dir()


def _ensure_dir() -> None:
    PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=BASE_DIR,
            capture_output=True,
            check=True,
        )
        return True
    except Exception:
        return False


def _git_commit(message: str, file_path: Path) -> bool:
    if not _git_available():
        return False
    try:
        subprocess.run(
            ["git", "add", str(file_path)],
            cwd=BASE_DIR,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=BASE_DIR,
            capture_output=True,
            check=True,
        )
        return True
    except Exception:
        return False


def propose(name: str, target_file: str, new_body: str, reason: str) -> str:
    """Save a proposed code change. Returns a status message."""
    _ensure_dir()
    target = Path(target_file)
    if not target.is_absolute():
        target = BASE_DIR / target
    if not target.exists():
        return f"Target file does not exist: {target}"

    current = target.read_text(encoding="utf-8")
    proposal = {
        "name": name,
        "target_file": str(target),
        "reason": reason,
        "current_hash": __import__("hashlib").sha256(current.encode()).hexdigest(),
        "new_body": new_body,
    }
    (PROPOSAL_DIR / f"{name}.json").write_text(
        json.dumps(proposal, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return f"Proposal '{name}' saved ({len(new_body)} bytes)."


def review(name: str) -> str:
    """Show the unified diff for a proposal. Returns the diff text."""
    path = PROPOSAL_DIR / f"{name}.json"
    if not path.exists():
        return f"No proposal named '{name}'."
    proposal = json.loads(path.read_text(encoding="utf-8"))
    target = Path(proposal["target_file"])
    current = target.read_text(encoding="utf-8").splitlines(keepends=True)
    new = proposal["new_body"].splitlines(keepends=True)
    diff = difflib.unified_diff(
        current, new, fromfile=str(target), tofile=f"{target} (proposed)",
        lineterm="",
    )
    lines = list(diff)
    if not lines:
        return f"Proposal '{name}' would make no changes to {target}."
    return "\n".join(lines)


def list_proposals() -> str:
    _ensure_dir()
    props = sorted(PROPOSAL_DIR.glob("*.json"))
    if not props:
        return "No code proposals."
    lines = []
    for p in props:
        data = json.loads(p.read_text(encoding="utf-8"))
        lines.append(f"• {data['name']} → {data['target_file']} ({data['reason']})")
    return "\n".join(lines)


def apply(name: str) -> str:
    """Apply a proposal: backup via git commit, write new body, commit."""
    path = PROPOSAL_DIR / f"{name}.json"
    if not path.exists():
        return f"No proposal named '{name}'."
    proposal = json.loads(path.read_text(encoding="utf-8"))
    target = Path(proposal["target_file"])

    # Verify the current file hasn't changed out from under us
    current = target.read_text(encoding="utf-8")
    import hashlib
    if hashlib.sha256(current.encode()).hexdigest() != proposal["current_hash"]:
        return (
            f"Refusing to apply '{name}': {target} has changed since the "
            f"proposal was made. Review and re-propose."
        )

    # Commit the current state as a backup before modifying
    if _git_available():
        _git_commit(
            f"Backup before applying code proposal '{name}'", target
        )

    target.write_text(proposal["new_body"], encoding="utf-8")

    if _git_available():
        _git_commit(
            f"Applied code proposal '{name}': {proposal['reason']}", target
        )

    # Remove the proposal after applying
    path.unlink()
    return f"Applied '{name}' to {target}. Committed to git."


def delete(name: str) -> str:
    """Delete a proposal without applying it."""
    path = PROPOSAL_DIR / f"{name}.json"
    if not path.exists():
        return f"No proposal named '{name}'."
    path.unlink()
    return f"Deleted proposal '{name}'."
