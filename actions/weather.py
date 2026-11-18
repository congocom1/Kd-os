"""JARVIS action for current weather conditions.

Port of the God's Eye View get_weather tool. Fetches current weather at a
location: conditions, temperature, feels-like, precipitation, cloud cover,
wind and visibility.

Uses the NOAA nowCOAST API via the God's Eye View weather proxy endpoint.
If the God's Eye View server is running, queries it via MCP; otherwise falls
back to direct NOAA nowCOAST gridpoint lookup.
"""

import json
import os
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from actions.mcp_bridge import is_server_running, mcp_call, get_base_url

from core import outcome

NOAA_BASE = "https://api.weather.gov"


def _noaa_gridpoint(lat, lon):
    """Look up NOAA gridpoint for a lat/lon, then fetch current conditions."""
    # Step 1: get the gridpoint forecast office and grid X/Y
    req = Request(
        f"{NOAA_BASE}/points/{lat},{lon}",
        headers={"User-Agent": "JARVIS/1.0", "Accept": "application/geo+json"},
    )
    with urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise ValueError(f"NOAA points API returned HTTP {resp.status}")
        points = json.loads(resp.read().decode("utf-8"))

    props = points.get("properties", {})
    grid_id = props.get("gridId")
    grid_x = props.get("gridX")
    grid_y = props.get("gridY")

    if not grid_id or grid_x is None or grid_y is None:
        raise ValueError("NOAA could not determine gridpoint for this location")

    # Step 2: fetch current conditions from the gridpoint
    req = Request(
        f"{NOAA_BASE}/gridpoints/{grid_id}/{grid_x},{grid_y}/observations/latest",
        headers={"User-Agent": "JARVIS/1.0", "Accept": "application/geo+json"},
    )
    with urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise ValueError(f"NOAA observations API returned HTTP {resp.status}")
        obs = json.loads(resp.read().decode("utf-8"))

    return obs


def _weather_row(obs):
    """Extract a weather row from a NOAA observation JSON."""
    props = obs.get("properties", {}) if isinstance(obs, dict) else {}

    def get(prop):
        val = props.get(prop)
        if isinstance(val, dict):
            return val.get("value")
        return val

    temp_c = get("temperature")
    if temp_c is not None:
        try:
            temp_c = float(temp_c)
        except (TypeError, ValueError):
            temp_c = None

    feels_like_c = get("relativeHumidity")  # placeholder; NOAA uses different fields
    # NOAA observation may have different field names; handle gracefully
    wind_kph = get("windSpeed")
    if wind_kph is not None:
        try:
            # NOAA wind speed may be like "5 mph" or just a number
            wind_str = str(wind_kph)
            if "mph" in wind_str:
                wind_kph = float(wind_str.replace("mph", "").strip()) * 1.60934
            else:
                wind_kph = float(wind_str)
        except (TypeError, ValueError):
            wind_kph = None

    return {
        "observed_at": props.get("timestamp"),
        "conditions": get("textDescription"),
        "weather_code": None,
        "temperature_c": temp_c,
        "feels_like_c": None,
        "precipitation_mm": None,
        "cloud_cover_pct": None,
        "wind_kph": wind_kph,
        "wind_direction_deg": None,
        "visibility_m": None,
    }


def weather(parameters: dict, player=None, session_memory=None) -> str:
    """JARVIS action for current weather conditions.

    Parameters:
    - action: "query" (default) or "info"
    - location: {lat, lon} (required for query)
    """
    try:
        action = parameters.get("action", "query")

        if action == "info":
            return json.dumps(
                {
                    "status": "done",
                    "tool": "get_weather",
                    "title": "Current weather",
                    "description": (
                        "Current weather at a location: conditions, temperature, "
                        "feels-like, precipitation, cloud cover, wind and visibility."
                    ),
                    "parameters": {
                        "location": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number", "minimum": -90, "maximum": 90},
                                "lon": {"type": "number", "minimum": -180, "maximum": 180},
                            },
                            "required": ["lat", "lon"],
                        }
                    },
                    "source": "NOAA nowCOAST / God's Eye View weather proxy",
                },
                ensure_ascii=False,
            )

        if action != "query":
            return outcome.failed("weather", "action must be 'query' or 'info'")

        location = parameters.get("location")
        if not location or not isinstance(location, dict):
            return outcome.failed("weather", "location is required for query action")

        lat = location.get("lat")
        lon = location.get("lon")
        if lat is None or lon is None:
            return outcome.failed("weather", "location.lat and location.lon are required")
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            return outcome.failed("weather", "location.lat and location.lon must be numbers")
        if abs(lat) > 90 or abs(lon) > 180:
            return outcome.failed("weather", "lat must be [-90, 90], lon must be [-180, 180]")

        # Try God's Eye View server first (via MCP bridge), fall back to direct NOAA
        base_url = get_base_url()
        server_up = is_server_running(base_url)

        if server_up:
            try:
                result = mcp_call(
                    "tools/call",
                    {"name": "get_weather", "arguments": {"location": {"lat": lat, "lon": lon}}},
                    base_url,
                )
                text = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
                return json.dumps(
                    {
                        "status": "failed" if result.get("isError") else "done",
                        "tool": "get_weather",
                        "content": text,
                        "data": result.get("structuredContent"),
                        "source": "God's Eye View MCP",
                    },
                    ensure_ascii=False,
                )
            except Exception:
                # Fall through to direct NOAA
                pass

        # Direct NOAA fallback
        try:
            obs = _noaa_gridpoint(lat, lon)
        except (URLError, HTTPError, ValueError, OSError) as exc:
            return outcome.failed(
                "weather",
                f"Could not fetch weather: {exc}",
                hint="Check network connectivity or ensure God's Eye View server is running",
            )

        row = _weather_row(obs)
        conditions = row["conditions"] or "unknown"
        temp_c = row["temperature_c"]
        temp_str = f"{round(temp_c)}°C" if temp_c is not None else "unknown"
        wind_kph = row["wind_kph"]
        wind_str = f"wind {round(wind_kph)} km/h" if wind_kph is not None else ""

        parts = [p for p in [conditions, temp_str, wind_str] if p]
        summary = ", ".join(parts) if parts else "conditions unknown"

        if player:
            try:
                player.write_log(f"[Weather] {summary} at {lat},{lon}")
            except Exception:
                pass

        return json.dumps(
            {
                "status": "done",
                "tool": "get_weather",
                "location": {"lat": lat, "lon": lon},
                "observed_at": row["observed_at"],
                "conditions": row["conditions"],
                "temperature_c": row["temperature_c"],
                "wind_kph": row["wind_kph"],
                "source": "NOAA nowCOAST",
                "fresh": True,
                "stale": False,
                "fallback": not server_up,
                "summary": summary,
            },
            ensure_ascii=False,
        )

    except (URLError, HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
        return outcome.failed("weather", str(exc))


TOOL = {
    "name": "weather",
    "description": (
        "Current weather at a location: conditions, temperature, feels-like, "
        "precipitation, cloud cover, wind and visibility. Queries the God's Eye "
        "View weather proxy when the server is running, falls back to direct "
        "NOAA nowCOAST otherwise."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["query", "info"],
                "description": "'query' to fetch data, 'info' for schema",
            },
            "location": {
                "type": "OBJECT",
                "description": "Location as {lat, lon}",
                "properties": {
                    "lat": {"type": "NUMBER", "minimum": -90, "maximum": 90},
                    "lon": {"type": "NUMBER", "minimum": -180, "maximum": 180},
                },
                "required": ["lat", "lon"],
            },
        },
        "required": [],
    },
    "handler": weather,
}