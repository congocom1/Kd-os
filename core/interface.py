"""
core/interface.py — Unified JARVIS Plugin/Action Interface

Single contract for all JARVIS extensions. Every action, plugin, and provider
exposes the same shape so they can be discovered, loaded, and invoked through
one unified entry point.

TOOL DECLARATION
    Every extension module exposes a module-level ``TOOL`` dict:

        TOOL = {
            "name": "my_action",              # unique snake_case identifier
            "kind": "action",                 # "action" | "plugin" | "provider"
            "label": "My Action",             # human-readable label
            "description": "What it does",    # description for the model
            "parameters": {                   # JSON Schema-like dict
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING", "description": "..."},
                },
                "required": ["action"],
            },
            "handler": run,                   # callable: run(parameters, player=None, session_memory=None) -> str
        }

HANDLER SIGNATURE
    All handlers share the same signature:

        def run(parameters: dict, player=None, session_memory=None) -> str:

    - ``parameters``: dict of user-supplied arguments
    - ``player``: JARVIS UI instance (has ``write_log``, ``speak``, ``session``)
    - ``session_memory``: session-scoped memory dict
    - Returns: a spoken/text response string

DISCOVERY
    Use ``discover_all()`` to find every action, plugin, and provider in one
    call. Returns a dict keyed by name with unified ``PluginRecord`` objects.

EXAMPLE
    from core.interface import discover_all, run_tool

    tools = discover_all()
    result = await run_tool(tools["studio_modeler"], {"action": "create", "otype": "box", "name": "cube", "size": "2,2,2"})
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from core.paths import get_base_dir as _get_base_dir

__all__ = [
    "PluginRecord",
    "discover_all",
    "run_tool",
    "discover_actions",
    "discover_plugins",
    "discover_providers",
]


@dataclass
class PluginRecord:
    """A discovered tool/plugin/action."""

    name: str
    kind: str  # "action" | "plugin" | "provider"
    label: str
    description: str
    parameters: dict
    handler: Callable
    file: str
    module: str
    enabled: bool = True


# ── Discovery ──────────────────────────────────────────────────────────────

def _load_module(module_name: str, file_path: Path):
    """Load a Python module from a file path without importing by name."""
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _discover_in_directory(
    directory: Path,
    kind: str,
    file_pattern: str = "*.py",
) -> dict[str, PluginRecord]:
    """Discover all TOOL-bearing modules in a directory."""
    results: dict[str, PluginRecord] = {}
    if not directory.is_dir():
        return results

    for path in sorted(directory.glob(file_pattern)):
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        try:
            module_name = f"{directory.name}_{path.stem}"
            module = _load_module(module_name, path)
            if module is None:
                continue

            tool = getattr(module, "TOOL", None) or getattr(module, "PLUGIN", None)
            if tool is None:
                continue

            name = tool.get("name") or path.stem
            if not name:
                continue

            rec = PluginRecord(
                name=name,
                kind=kind,
                label=tool.get("label", name),
                description=tool.get("description", ""),
                parameters=tool.get("parameters", {"type": "OBJECT", "properties": {}}),
                handler=tool.get("handler") or getattr(module, "run", None),
                file=str(path),
                module=module_name,
                enabled=True,
            )
            results[name] = rec
        except Exception:
            continue

    return results


def discover_actions(actions_dir: Path | str = None) -> dict[str, PluginRecord]:
    """Discover all action modules in ``actions/``."""
    if actions_dir is None:
        actions_dir = _get_base_dir() / "actions"
    return _discover_in_directory(Path(actions_dir), "action", "*.py")


def discover_plugins(plugins_dir: Path | str = None) -> dict[str, PluginRecord]:
    """Discover all plugin modules in ``plugins/``."""
    if plugins_dir is None:
        plugins_dir = _get_base_dir() / "plugins"
    return _discover_in_directory(Path(plugins_dir), "plugin", "*.py")


def discover_providers(providers_dir: Path | str = None) -> dict[str, PluginRecord]:
    """Discover all provider modules in ``providers/``."""
    if providers_dir is None:
        providers_dir = _get_base_dir() / "providers"
    return _discover_in_directory(Path(providers_dir), "provider", "*.py")


def discover_all(
    actions_dir: Path | str = None,
    plugins_dir: Path | str = None,
    providers_dir: Path | str = None,
) -> dict[str, PluginRecord]:
    """Discover all actions, plugins, and providers in one call.

    Returns a dict keyed by name. Later discoveries override earlier ones
    if names collide (actions take priority over plugins over providers).
    """
    all_tools: dict[str, PluginRecord] = {}

    # Providers first (lowest priority), then plugins, then actions (highest)
    for results in (
        discover_providers(providers_dir),
        discover_plugins(plugins_dir),
        discover_actions(actions_dir),
    ):
        all_tools.update(results)

    return all_tools


# ── Execution ──────────────────────────────────────────────────────────────

async def run_tool(
    rec: PluginRecord,
    parameters: dict | None = None,
    player=None,
    session_memory=None,
) -> str:
    """Run a tool/plugin/action by its PluginRecord."""
    if rec is None:
        raise ValueError("No tool record provided")
    if rec.handler is None:
        raise ValueError(f"Tool '{rec.name}' has no handler")

    parameters = parameters or {}
    try:
        # Check if handler is async
        if asyncio.iscoroutinefunction(rec.handler):
            result = await rec.handler(parameters, player=player, session_memory=session_memory)
        else:
            result = rec.handler(parameters, player=player, session_memory=session_memory)
        return result or "Done."
    except Exception as e:
        return f"Error running '{rec.name}': {e}"


def run_tool_sync(
    rec: PluginRecord,
    parameters: dict | None = None,
    player=None,
    session_memory=None,
) -> str:
    """Synchronous wrapper around run_tool."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(run_tool(rec, parameters, player, session_memory))


# ── Convenience: run by name ─────────────────────────────────────────────

async def run_by_name(
    name: str,
    parameters: dict | None = None,
    player=None,
    session_memory=None,
    actions_dir: Path | str = None,
    plugins_dir: Path | str = None,
    providers_dir: Path | str = None,
) -> str:
    """Run a tool by name, discovering it first if needed."""
    tools = discover_all(actions_dir, plugins_dir, providers_dir)
    if name not in tools:
        available = ", ".join(sorted(tools.keys()))
        return f"Unknown tool '{name}'. Available: {available}"
    return await run_tool(tools[name], parameters, player, session_memory)


def run_by_name_sync(
    name: str,
    parameters: dict | None = None,
    player=None,
    session_memory=None,
    actions_dir: Path | str = None,
    plugins_dir: Path | str = None,
    providers_dir: Path | str = None,
) -> str:
    """Synchronous wrapper around run_by_name."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        run_by_name(name, parameters, player, session_memory, actions_dir, plugins_dir, providers_dir)
    )
