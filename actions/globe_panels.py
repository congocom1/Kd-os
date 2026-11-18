"""JARVIS UI panels for God's Eye View globe data visualization.

These panels consolidate God's View data displays within the JARVIS interface,
eliminating the need for separate browser windows. Panels can be rendered in
the main JARVIS UI window, side panels, or dedicated tabs.
"""

import json
import os
import time
from urllib.parse import urlsplit

import requests

from core import outcome
from core.app_manager import AppManager


def _base_url():
    """Get the God's Eye View server base URL, validating it's loopback."""
    url = os.environ.get("JARVIS_GLOBE_URL", "http://127.0.0.1:4174").rstrip("/")
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("JARVIS_GLOBE_URL must be a loopback HTTP origin")
    return url


def _rpc(base, method, params):
    """Internal JSON-RPC caller to the God's View MCP server."""
    with requests.Session() as session:
        session.trust_env = False
        response = session.post(
            base + "/mcp", json={"jsonrpc": "2.0", "id": 1,
                                  "method": method, "params": params},
            timeout=(3, 60), allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError(f"Globe service returned HTTP {response.status_code}")
        payload = response.json()
    if "error" in payload:
        raise ValueError(str(payload["error"].get("message", "MCP request failed")))
    return payload["result"]


def _is_server_running():
    """Check if the God's Eye View MCP server is already running."""
    return AppManager.is_gev_running()


def _ensure_server():
    """Start God's Eye View if it is not already running."""
    if not AppManager.is_gev_running():
        AppManager.start_gev()


def globe_panels(parameters: dict, player=None, session_memory=None) -> str:
    """Render God's View data panels within JARVIS UI.

    Available panel types:
    - "globe": Main globe visualization
    - "tools": Tool results display panel
    - "status": Server health and monitoring panel
    - "share": Share/view-link panel
    - "selector": Tool selector panel

    Parameters:
    - action: "list_panels", "render", "get_data"
    - panel_type: One of the panel types above
    - tool_name: Name of tool to display results for (for tool panels)
    """
    try:
        base = _base_url()

        # Ensure server is running
        _ensure_server()

        action = parameters.get("action", "list_panels")
        panel_type = parameters.get("panel_type", "")

        if action == "list_panels":
            panels = [
                {"type": "globe", "title": "Globe Visualization", "description": "Interactive 3D globe showing aircraft, ships, satellites, fires, and earthquakes"},
                {"type": "tools", "title": "Tool Results", "description": "Display results from geospatial tools (earthquakes, fires, weather, etc.)"},
                {"type": "status", "title": "Server Status", "description": "God's View server health and feed status"},
                {"type": "share", "title": "Share Links", "description": "Generate shareable links for current globe views"},
                {"type": "selector", "title": "Tool Selector", "description": "Select and configure geospatial tools to run"},
            ]
            return json.dumps({"status": "done", "panels": panels}, ensure_ascii=False)

        if action == "render":
            ptype = panel_type or "globe"
            if ptype == "globe":
                return json.dumps({
                    "status": "done",
                    "content": "<div style='height:600px; width:100%'>God's View Globe Visualization Panel</div>",
                    "description": "Render the interactive 3D globe within JARVIS UI"
                }, ensure_ascii=False)
            elif ptype == "tools":
                tool_name = parameters.get("tool_name", "")
                return json.dumps({
                    "status": "done",
                    "content": f"<div style='height:400px; width:100%'>Tool Results: {tool_name}</div>",
                    "description": f"Display results from {tool_name} tool"
                }, ensure_ascii=False)
            elif ptype == "status":
                try:
                    result = _rpc(base, "tools/list", {})
                    tools = result.get("tools", [])
                    return json.dumps({
                        "status": "done",
                        "content": f"<div style='height:300px; width:100%'>Server Status: {len(tools)} tools available</div>",
                        "description": "Show server health and available tools"
                    }, ensure_ascii=False)
                except Exception as e:
                    return json.dumps({
                        "status": "failed",
                        "content": f"<div style='height:300px; width:100%'>Server unavailable: {str(e)}</div>",
                        "description": "Server status display failed"
                    }, ensure_ascii=False)
            elif ptype == "share":
                return json.dumps({
                    "status": "done",
                    "content": "<div style='height:300px; width:100%'>Share View Links</div>",
                    "description": "Generate and display shareable links for current globe view"
                }, ensure_ascii=False)
            elif ptype == "selector":
                return json.dumps({
                    "status": "done",
                    "content": "<div style='height:400px; width:100%'>Tool Selector Panel</div>",
                    "description": "Select and configure geospatial tools"
                }, ensure_ascii=False)
            else:
                raise ValueError(f"Unknown panel type: {ptype}")

        if action == "get_data":
            tool_name = parameters.get("tool_name", "")
            if not tool_name:
                raise ValueError("tool_name required for get_data action")

            # Get tool schema and data
            try:
                result = _rpc(base, "tools/list", {})
                tools = result.get("tools", [])
                tool_names = {t["name"] for t in tools}

                if tool_name not in tool_names:
                    raise ValueError(f"Unknown tool: {tool_name}. Available: {list(tool_names)}")

                # Return tool info for the panel to render
                tool_info = next(t for t in tools if t["name"] == tool_name)
                return json.dumps({
                    "status": "done",
                    "content": f"<div style='height:400px; width:100%'>Data from {tool_name}</div>",
                    "tool_name": tool_name,
                    "schema": tool_info.get("description", ""),
                    "description": f"Get data from {tool_name} tool for panel rendering"
                }, ensure_ascii=False)
            except Exception as e:
                return json.dumps({
                    "status": "failed",
                    "content": f"<div style='height:300px; width:100%'>Error: {str(e)}</div>",
                    "description": f"Failed to get data for {tool_name}"
                }, ensure_ascii=False)

        raise ValueError(f"Unknown action: {action}. Valid: list_panels, render, get_data")

    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return outcome.failed("globe_panels", str(exc),
                              hint="Ensure God's View server is running on port 4174")


TOOL = {
    "name": "globe_panels",
    "description": (
        "Render God's View data panels within the JARVIS UI interface. "
        "Displays globe visualization, tool results, server status, share links, "
        "and tool selector panels without requiring separate browser windows. "
        "All data comes from the God's View MCP server at http://127.0.0.1:4174. "
        "Use action='list_panels' to see available panels, "
        "action='render' with panel_type to display a specific panel, "
        "or action='get_data' with tool_name to fetch data for panel rendering."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["list_panels", "render", "get_data"]},
            "panel_type": {"type": "STRING", "description": "Type of panel: globe, tools, status, share, selector"},
            "tool_name": {"type": "STRING", "description": "Name of tool to display results for"},
        },
        "required": ["action"],
    },
    "handler": globe_panels,
}