"""Unified MCP bridge for JARVIS actions.

Provides a single MCP client used by all JARVIS actions that need to talk to
the God's Eye View server. Features automatic server detection, health-check,
and graceful fallback when the server is unavailable.

All actions that need God's Eye View data should use this bridge instead of
opening their own HTTP connections.
"""

import json
import os
import time
import logging
logger = logging.getLogger(__name__)
from urllib.parse import urlsplit
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from core import outcome

DEFAULT_BASE_URL = "http://127.0.0.1:4174"
_MCP_ENDPOINT = "/mcp"
_HEALTH_ENDPOINT = "/"

# Module-level cache: last known good state
_state = {
    "base_url": None,
    "last_health_check": 0.0,
    "last_health_ok": False,
    "server_unavailable_since": None,
}

HEALTH_CHECK_INTERVAL = 5.0  # seconds between health checks


def _validate_base_url(url):
    """Validate that url is a loopback HTTP origin."""
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("MCP bridge URL must be a loopback HTTP origin")
    return url


def get_base_url():
    """Return the configured God's Eye View base URL, validating loopback."""
    url = os.environ.get("JARVIS_GLOBE_URL", DEFAULT_BASE_URL).rstrip("/")
    return _validate_base_url(url)


def is_server_running(base_url=None, force=False):
    """Check if the God's Eye View MCP server is reachable.

    Uses a short cache (5s) to avoid hammering a down server. Set force=True
    to bypass the cache.
    """
    base_url = base_url or get_base_url()
    now = time.time()

    if not force and _state["last_health_ok"] and now - _state["last_health_check"] < HEALTH_CHECK_INTERVAL:
        return True

    try:
        req = Request(base_url + _HEALTH_ENDPOINT, headers={"User-Agent": "JARVIS-MCP-Bridge/1.0"})
        with urlopen(req, timeout=2) as resp:
            ok = resp.status == 200
    except Exception:
        ok = False

    _state["last_health_check"] = now
    _state["last_health_ok"] = ok

    if ok:
        _state["server_unavailable_since"] = None
    else:
        if _state["server_unavailable_since"] is None:
            _state["server_unavailable_since"] = now

    return ok


def server_unavailable_duration():
    """Return seconds since the server first became unavailable, or 0."""
    if _state["server_unavailable_since"] is None:
        return 0.0
    return time.time() - _state["server_unavailable_since"]


def mcp_call(method, params=None, base_url=None, timeout=(3, 60)):
    """Make a JSON-RPC call to the God's Eye View MCP server.

    Returns the ``result`` field on success. Raises ValueError on error
    responses, URLError/HTTPError on transport failure.

    Parameters:
    - method: MCP method name (e.g. "tools/list", "tools/call")
    - params: dict of parameters (default {})
    - base_url: override server URL (default from env/DEFAULT)
    - timeout: (connect, read) timeout tuple
    """
    base_url = base_url or get_base_url()
    params = params or {}

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    data = json.dumps(payload).encode("utf-8")

    req = Request(
        base_url + _MCP_ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "JARVIS-MCP-Bridge/1.0",
        },
        method="POST",
    )

    with urlopen(req, timeout=timeout[0]) as resp:
        if resp.status != 200:
            raise ValueError(f"Globe service returned HTTP {resp.status}")
        body = resp.read().decode("utf-8")

    result = json.loads(body)

    if "error" in result:
        raise ValueError(str(result["error"].get("message", "MCP request failed")))

    return result["result"]


def tools_list(base_url=None):
    """List available tools from the God's Eye View MCP server."""
    return mcp_call("tools/list", {}, base_url)


def tools_call(name, arguments, base_url=None):
    """Call a named tool on the God's Eye View MCP server."""
    return mcp_call("tools/call", {"name": name, "arguments": arguments}, base_url)


def call_with_fallback(method, params=None, base_url=None, fallback=None):
    """Call MCP with an automatic fallback value on failure.

    Returns the MCP result on success, or ``fallback`` on any error. Never
    raises. Use this for actions that should degrade gracefully.
    """
    try:
        return mcp_call(method, params, base_url)
    except Exception:
        return fallback


def health():
    """Return server health status as a dict.

    Keys: status ("reachable"|"unavailable"), url, unavailable_for (seconds).
    """
    base_url = get_base_url()
    ok = is_server_running(base_url)
    return {
        "status": "reachable" if ok else "unavailable",
        "url": base_url,
        "unavailable_for": round(server_unavailable_duration(), 1),
    }


def require_server():
    """Ensure the server is reachable, returning an outcome.failed string if not.

    Returns None when the server is reachable, otherwise an outcome.failed()
    result string that callers can return directly.
    """
    if not is_server_running():
        return outcome.failed(
            "mcp_bridge",
            f"God's Eye View server not reachable at {get_base_url()}",
            hint="Start the server with launch.sh or globe:start",
        )
    return None


TOOL = {
    "name": "mcp_bridge",
    "description": (
        "Unified MCP bridge for the God's Eye View server. Provides health "
        "checks, server status, and JSON-RPC calls to the local MCP endpoint. "
        "All JARVIS actions that need God's Eye View data use this bridge. "
        "Use action='health' to check server status, action='list' to enumerate "
        "available tools, or action='call' to invoke a specific tool."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["health", "list", "call"],
                "description": "'health' for server status, 'list' for tools, 'call' to invoke",
            },
            "tool": {
                "type": "STRING",
                "description": "Tool name for action='call'",
            },
            "arguments_json": {
                "type": "STRING",
                "description": "JSON object of tool arguments for action='call'",
            },
        },
        "required": ["action"],
    },
    "handler": None,  # set below after function def
}


def mcp_bridge(parameters: dict, player=None, session_memory=None) -> str:
    """JARVIS action handler for the unified MCP bridge."""
    try:
        action = parameters.get("action", "health")

        if action == "health":
            return json.dumps(health(), ensure_ascii=False)

        if action == "list":
            fail = require_server()
            if fail:
                return fail
            result = tools_list()
            tools = result.get("tools", []) if isinstance(result, dict) else []
            return json.dumps(
                {"status": "done", "tools": tools, "count": len(tools)},
                ensure_ascii=False,
            )

        if action == "call":
            fail = require_server()
            if fail:
                return fail
            name = parameters.get("tool", "")
            if not name:
                return outcome.failed("mcp_bridge", "tool name required for action='call'")
            arguments = json.loads(parameters.get("arguments_json", "{}"))
            if not isinstance(arguments, dict):
                return outcome.failed("mcp_bridge", "arguments_json must encode an object")
            result = tools_call(name, arguments)
            text = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
            return json.dumps(
                {
                    "status": "failed" if result.get("isError") else "done",
                    "tool": name,
                    "content": text,
                    "data": result.get("structuredContent"),
                },
                ensure_ascii=False,
            )

        raise ValueError("action must be health, list, or call")

    except (URLError, HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
        return outcome.failed("mcp_bridge", str(exc))


TOOL["handler"] = mcp_bridge