"""JARVIS action for recent orbital launches.

Port of the God's Eye View get_recent_launches tool. Fetches orbital launches
from Launch Library 2 over the last 30 days, newest first, with provider,
rocket, pad, mission and outcome.

Parameters:
- limit: max results (default 25, max 200)
"""

import json
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from core import outcome

LL2_BASE = "https://ll2.api.space"


def _ll2_recent_url(end=None):
    """Build the Launch Library 2 recent-launches URL for the last 30 days."""
    if end is None:
        end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    return (
        f"{LL2_BASE}/2.2.0/launch/"
        f"?start={start.strftime('%Y-%m-%d')}"
        f"&end={end.strftime('%Y-%m-%d')}"
        f"&orderby=-net"
    )


def launches(parameters: dict, player=None, session_memory=None) -> str:
    """JARVIS action for recent orbital launches from Launch Library 2.

    Parameters:
    - action: "query" (default) or "info"
    - limit: max results (default 25, max 200)
    """
    try:
        action = parameters.get("action", "query")

        if action == "info":
            return json.dumps(
                {
                    "status": "done",
                    "tool": "get_recent_launches",
                    "title": "Recent launches",
                    "description": (
                        "Orbital launches from Launch Library 2 over the last 30 "
                        "days, newest first, with provider, rocket, pad, mission "
                        "and outcome."
                    ),
                    "parameters": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 200,
                            "description": "Most rows to return (default 25)",
                        }
                    },
                    "source": "Launch Library 2",
                },
                ensure_ascii=False,
            )

        if action != "query":
            return outcome.failed("launches", "action must be 'query' or 'info'")

        limit = parameters.get("limit", 25)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return outcome.failed("launches", "limit must be an integer")
        if limit < 1 or limit > 200:
            return outcome.failed("launches", "limit must be between 1 and 200")

        url = _ll2_recent_url()
        try:
            req = Request(url, headers={"User-Agent": "JARVIS/1.0", "Accept": "application/json"})
            with urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    raise ValueError(f"Launch Library 2 returned HTTP {resp.status}")
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, HTTPError, ValueError, OSError) as exc:
            return outcome.failed(
                "launches",
                f"Could not reach Launch Library 2: {exc}",
                hint="Check network connectivity",
            )

        launches_list = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(launches_list, list):
            return outcome.failed("launches", "Launch feed returned no launches")

        rows = []
        for launch in launches_list:
            if not isinstance(launch, dict):
                continue
            name = launch.get("name")
            if not name:
                continue
            rocket_cfg = launch.get("rocket", {}) or {}
            rocket_config = rocket_cfg.get("configuration", {}) or {}
            provider = launch.get("launch_service_provider", {}) or {}
            pad = launch.get("pad", {}) or {}
            pad_location = pad.get("location", {}) or {}
            mission = launch.get("mission", {}) or {}
            orbit = mission.get("orbit", {}) or {}

            rows.append({
                "id": str(launch.get("id") or ""),
                "name": str(name),
                "time": str(launch.get("net") or ""),
                "status": str((launch.get("status") or {}).get("name") or ""),
                "provider": str(provider.get("name") or ""),
                "rocket": str(
                    rocket_config.get("full_name")
                    or rocket_config.get("name")
                    or ""
                ),
                "pad": str(pad.get("name") or ""),
                "location": str(pad_location.get("name") or ""),
                "mission": str(mission.get("name") or ""),
                "orbit": str(orbit.get("name") or ""),
            })

        # Sort newest first
        rows.sort(key=lambda r: r["time"], reverse=True)

        # Apply limit
        rows = rows[:limit]

        count = len(rows)

        if player:
            try:
                player.write_log(f"[Launches] {count} orbital launches (last 30 days)")
            except Exception:
                pass

        latest = rows[0]["name"] if rows else None
        return json.dumps(
            {
                "status": "done",
                "tool": "get_recent_launches",
                "count": count,
                "source": "Launch Library 2",
                "fresh": True,
                "stale": False,
                "launches": rows,
                "summary": (
                    f"{count} launch(es) in the last 30 days"
                    + (f"; latest {latest}" if latest else ".")
                ),
            },
            ensure_ascii=False,
        )

    except (URLError, HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
        return outcome.failed("launches", str(exc))


TOOL = {
    "name": "launches",
    "description": (
        "Orbital launches from Launch Library 2 over the last 30 days, newest "
        "first, with provider, rocket, pad, mission and outcome."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["query", "info"],
                "description": "'query' to fetch data, 'info' for schema",
            },
            "limit": {
                "type": "INTEGER",
                "minimum": 1,
                "maximum": 200,
                "description": "Maximum results (default 25)",
            },
        },
        "required": [],
    },
    "handler": launches,
}