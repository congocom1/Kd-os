"""JARVIS adapter for the local God's Eye View MCP service.

Server lifecycle is handled by core.app_manager so the same orchestration can
be reused by the UI, other actions, and shutdown hooks.
"""

import json
import time
import webbrowser

import requests

from actions.mcp_bridge import (
    get_base_url,
    mcp_call,
    health as mcp_health,
)
from core import outcome
from core.app_manager import AppManager


def _base_url():
    """Get the God's Eye View base URL, validating loopback."""
    return get_base_url()


def _rpc(base, method, params):
    """Internal RPC caller - delegates to mcp_bridge.mcp_call.

    Kept as a separate function so tests can patch it (test_globe.py patches
    actions.globe._rpc).
    """
    return mcp_call(method, params, base)


def _is_server_running():
    """Check if the God's Eye View MCP server is already running."""
    return AppManager.is_gev_running()


def _start_server():
    """Start the God's Eye View Vite server in the background."""
    return AppManager.start_gev()


def _stop_server():
    """Stop the God's Eye View MCP server."""
    return AppManager.stop_gev()


def globe(parameters: dict, player=None, session_memory=None) -> str:
    """JARVIS adapter for the local God's Eye View MCP service."""
    try:
        base = _base_url()
        action = parameters.get("action", "")

        # Only auto-start server for "call" actions; read-only actions fail cleanly.
        if action == "call" and not _is_server_running():
            result = _start_server()
            if result.get("status") not in ("started", "already_running"):
                return json.dumps({
                    "status": "failed",
                    "reason": f"Could not start God's Eye View server: {result}",
                    "hint": "Ensure node/npm are available or start server manually"
                }, ensure_ascii=False)

        if action == "status":
            result = _rpc(base, "tools/list", {})
            count = sum(t["name"] != "panel_request" for t in result.get("tools", []))
            return json.dumps({
                "status": "done",
                "url": base,
                "tools_available": count,
                "service": "reachable",
                "live_feeds_verified": False,
            }, ensure_ascii=False)

        if action == "open":
            opened = webbrowser.open(base)
            return outcome.unverified(
                "globe",
                "Browser launch requested; rendering not verified",
                url=base,
                browser_accepted=bool(opened),
            )

        if action == "list":
            result = _rpc(base, "tools/list", {})
            tools = [t for t in result.get("tools", []) if t["name"] != "panel_request"]
            return json.dumps({"status": "done", "tools": tools}, ensure_ascii=False)

        if action == "start":
            result = _start_server()
            if result.get("status") == "already_running":
                return json.dumps({"status": "done", "url": base, "note": "Server already running"}, ensure_ascii=False)
            if result.get("status") == "started":
                return json.dumps({"status": "done", "url": base, "note": "Server started successfully"}, ensure_ascii=False)
            return json.dumps({"status": "failed", "reason": f"Could not start server: {result}"}, ensure_ascii=False)

        if action == "stop":
            result = _stop_server()
            if result.get("status") == "stopped":
                return json.dumps({"status": "done", "note": "Server stopped successfully"}, ensure_ascii=False)
            return json.dumps({"status": "failed", "reason": f"Could not stop server: {result}"}, ensure_ascii=False)

        if action == "restart":
            _stop_server()
            time.sleep(1)
            start_result = _start_server()
            if start_result.get("status") in ("started", "already_running"):
                return json.dumps({"status": "done", "url": base, "note": "Server restarted successfully"}, ensure_ascii=False)
            return json.dumps({"status": "failed", "reason": f"Restart failed: {start_result}"}, ensure_ascii=False)

        if action == "health":
            h = mcp_health()
            return json.dumps({"status": "done", "service": h["status"], "url": h["url"]}, ensure_ascii=False)

        if action != "call":
            raise ValueError("action must be status, open, list, call, start, stop, restart, or health")

        name = parameters.get("tool", "")
        tools = _rpc(base, "tools/list", {}).get("tools", [])
        if name == "panel_request" or name not in {t["name"] for t in tools}:
            raise ValueError("Unknown or internal tool; use action=list first")

        arguments = json.loads(parameters.get("arguments_json", "{}"))
        if not isinstance(arguments, dict):
            raise ValueError("arguments_json must encode an object")

        result = _rpc(base, "tools/call", {"name": name, "arguments": arguments})
        text = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
        return json.dumps({
            "status": "failed" if result.get("isError") else "done",
            "tool": name,
            "content": text,
            "data": result.get("structuredContent"),
        }, ensure_ascii=False)

    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return outcome.failed("globe", str(exc),
                              hint="Start the globe with action=start, or run apps/gods-eye-view manually.")


TOOL = {
    "name": "globe",
    "description": (
        "Check status, open God's Eye View or query its local geospatial tools: aircraft, ships, satellites, "
        "fires, quakes, infrastructure and shareable globe views. First use list to get exact "
        "tool names and input schemas, then call with arguments_json. Preserve stale/fallback "
        "warnings. Returned view links do not control an already-open browser tab. "
        "Cockpit, weather timeline, director and other interactive controls are in the globe UI. "
        "Server starts automatically on first use if not already running. "
        "Use actions: start, stop, restart, health to manage the server lifecycle."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: status, open, list, call, start, stop, restart, health",
            },
            "tool": {
                "type": "STRING",
                "description": "Tool name to call (required when action=call)",
            },
            "arguments_json": {
                "type": "STRING",
                "description": "JSON object string of arguments for the tool (required when action=call)",
            },
        },
        "required": ["action"],
    },
    "handler": globe,
}
