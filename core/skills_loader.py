"""
core/skills_loader.py — Discover and load skill definitions from multiple formats.

Supported skill formats:

1. SKILL.md (Claude Code / wakejarvis.ai format)
   YAML frontmatter followed by markdown body instructions.

2. skill.yaml + skill.py (Grominet95 jarvis-skills format)
   skill.yaml provides metadata (name, description, tags).
   skill.py contains a SYSTEM_PROMPT string with the skill instructions.

A skill is a directory containing either a SKILL.md file or both a
skill.yaml and skill.py file. The loader reads the metadata and keeps the
skill's instructions (SYSTEM_PROMPT or markdown body) as the skill content.

Skills are NOT executable code — they are agent instructions. When a skill is
invoked, its content is prepended to the Live session's system instruction so
the model adopts that persona and workflow for the remainder of the
conversation (or until the user switches skills).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class SkillRecord:
    """A discovered skill."""

    name: str
    description: str
    path: Path               # directory containing the skill files
    markdown: str            # skill instructions (SYSTEM_PROMPT or SKILL.md body)
    body: str                # same as markdown (kept for compatibility)
    frontmatter: dict        # parsed YAML metadata
    allowed_tools: list[str] = field(default_factory=list)
    format: str = "unknown"  # "skill-md" or "skill-yaml"
    source: str = ""         # which collection the skill came from

    @property
    def skill_file(self) -> Path:
        """Primary skill file path."""
        if self.format == "skill-yaml":
            return self.path / "skill.yaml"
        return self.path / "SKILL.md"


_YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Match SYSTEM_PROMPT = """...""" or SYSTEM_PROMPT = '''...'''
_SYSTEM_PROMPT_RE = re.compile(
    r"SYSTEM_PROMPT\s*=\s*(?:r?['\"]{3})(.*?)(?:['\"]{3})",
    re.DOTALL,
)


def _extract_system_prompt(py_file: Path) -> Optional[str]:
    """Extract the SYSTEM_PROMPT string from a skill.py file without importing it.

    The skill.py files import from `skills.base import SkillBase` which doesn't
    exist in this project, so we can't import them. Instead, we parse the AST
    to find the SYSTEM_PROMPT assignment and extract its string value.
    """
    try:
        text = py_file.read_text(encoding="utf-8")
    except Exception:
        return None

    # First try regex for simple cases
    match = _SYSTEM_PROMPT_RE.search(text)
    if match:
        return match.group(1).strip()

    # Fall back to AST parsing for more complex cases
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SYSTEM_PROMPT":
                    if isinstance(node.value, ast.Constant) and isinstance(
                        node.value.value, str
                    ):
                        return node.value.value.strip()
                    # Handle implicit string concatenation
                    if isinstance(node.value, ast.JoinedStr):
                        parts = []
                        for part in node.value.values:
                            if isinstance(part, ast.Constant) and isinstance(
                                part.value, str
                            ):
                                parts.append(part.value)
                        if parts:
                            return "".join(parts).strip()
    return None


def _parse_skill_md(skill_file: Path) -> Optional[SkillRecord]:
    """Parse a single SKILL.md file into a SkillRecord, or None on failure."""
    try:
        text = skill_file.read_text(encoding="utf-8")
    except Exception:
        return None

    match = _YAML_FRONTMATTER_RE.match(text)
    if not match:
        return None

    frontmatter_text = match.group(1)
    body = text[match.end():]

    try:
        fm = yaml.safe_load(frontmatter_text) or {}
    except Exception:
        fm = {}

    name = fm.get("name") or skill_file.parent.name
    description = fm.get("description") or ""
    allowed = fm.get("allowed-tools", [])
    if isinstance(allowed, str):
        allowed = [t.strip() for t in allowed.split(",")]
    elif not isinstance(allowed, list):
        allowed = []

    return SkillRecord(
        name=str(name),
        description=str(description),
        path=skill_file.parent,
        markdown=text,
        body=body.strip(),
        frontmatter=fm,
        allowed_tools=allowed,
        format="skill-md",
    )


def _parse_skill_yaml(skill_dir: Path) -> Optional[SkillRecord]:
    """Parse a skill.yaml + skill.py directory into a SkillRecord, or None on failure."""
    yaml_file = skill_dir / "skill.yaml"
    py_file = skill_dir / "skill.py"

    if not yaml_file.is_file() or not py_file.is_file():
        return None

    try:
        yaml_text = yaml_file.read_text(encoding="utf-8")
    except Exception:
        return None

    try:
        fm = yaml.safe_load(yaml_text) or {}
    except Exception:
        return None

    if not isinstance(fm, dict):
        return None

    name = fm.get("name") or skill_dir.name
    description = fm.get("description") or ""
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    elif not isinstance(tags, list):
        tags = []

    # Extract SYSTEM_PROMPT from skill.py
    system_prompt = _extract_system_prompt(py_file)
    if system_prompt is None:
        return None

    # Build markdown content from SYSTEM_PROMPT + metadata header
    header = f"""# {name}

{description}

Tags: {', '.join(tags) if tags else 'none'}

Source: Grominet95 jarvis-skills
"""

    markdown = header + "\n\n---\n\n" + system_prompt

    return SkillRecord(
        name=str(name),
        description=str(description),
        path=skill_dir,
        markdown=markdown,
        body=system_prompt,
        frontmatter=fm,
        allowed_tools=tags,
        format="skill-yaml",
    )


def discover_skills(skills_dir: Path, source: str = "") -> dict[str, SkillRecord]:
    """Scan skills_dir for skill files and return name -> SkillRecord.

    skills_dir is expected to contain vendor subdirectories, each of which may
    contain one or more skill directories. Two formats are supported:

    1. SKILL.md files (Claude Code / wakejarvis.ai format)
    2. skill.yaml + skill.py pairs (Grominet95 jarvis-skills format)
    """
    skills: dict[str, SkillRecord] = {}
    if not skills_dir.is_dir():
        return skills

    # Scan for SKILL.md files
    for skill_file in sorted(skills_dir.rglob("SKILL.md")):
        rec = _parse_skill_md(skill_file)
        if rec is None:
            continue
        if rec.name in skills:
            continue  # first discovery wins
        rec.source = source
        skills[rec.name] = rec

    # Scan for skill.yaml + skill.py directories
    for yaml_file in sorted(skills_dir.rglob("skill.yaml")):
        skill_dir = yaml_file.parent
        rec = _parse_skill_yaml(skill_dir)
        if rec is None:
            continue
        if rec.name in skills:
            continue  # first discovery wins
        rec.source = source
        skills[rec.name] = rec

    return skills


# Skill collections scanned, relative to the app base dir: the bundled vendor
# repos first, then the awesome-llm-apps agent_skills collection.
SKILL_COLLECTIONS = (
    ("skills", "vendor"),
    ("awesome-llm-apps-main/agent_skills", "awesome-llm-apps"),
)


def discover_all_skills(base_dir: Path) -> dict[str, SkillRecord]:
    """Discover skills from every collection under base_dir.

    First discovery of a name wins; later duplicates are skipped with a log
    line so a vendored skill can shadow a collection skill deliberately.
    """
    import logging

    log = logging.getLogger("jarvis.skills")
    skills: dict[str, SkillRecord] = {}
    for rel, source in SKILL_COLLECTIONS:
        for name, rec in discover_skills(base_dir / rel, source=source).items():
            if name in skills:
                log.warning("skill name collision: %r from %s shadowed by %s",
                            name, source, skills[name].source)
                continue
            skills[name] = rec
    return skills


def load_skill_markdown(skill: SkillRecord) -> str:
    """Return the full skill content for injection into a system instruction."""
    return skill.markdown
