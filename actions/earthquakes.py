"""JARVIS action for recent earthquake data from the USGS feed.

Port of the God's Eye View get_earthquakes tool to a standalone JARVIS
Python action. Fetches M2.5+ earthquakes from the USGS all-day GeoJSON feed
directly — no dependency on the God's View server being running.

Parameters match the God's View tool schema:
- area: object with exactly one of place (string), bbox ([west, south, east, north]),
        or lat + lon with optional radius_km
- min_magnitude: minimum magnitude (default 2.5, max 10)
- limit: max results (default 25, max 200)

Returns structured results that mirror the God's View tool output,
including stale/fallback flags when applicable.
"""

import json
import math
import os
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from core import outcome

USGS_API_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)


def _usgs_fetch():
    """Fetch the USGS all-day earthquake GeoJSON feed."""
    req = Request(USGS_API_URL, headers={"User-Agent": "JARVIS/1.0"})
    with urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise ValueError(f"USGS returned HTTP {response.status}")
        data = json.loads(response.read().decode("utf-8"))
    return data


def _normalize_snapshot(geojson):
    """Validate and normalize a USGS GeoJSON feed into row dicts.

    Mirrors the JavaScript normalizeEarthquakeSnapshot logic.
    Returns a list of row dicts or raises ValueError on malformed data.
    """
    if not isinstance(geojson, dict) or not isinstance(
        geojson.get("features"), list
    ):
        raise ValueError("Malformed USGS response: missing features array")

    rows = []
    seen_ids = set()

    for index, feature in enumerate(geojson["features"]):
        try:
            geometry = feature.get("geometry")
            properties = feature.get("properties")

            if not geometry or not properties:
                continue

            coords = geometry.get("coordinates")
            if (
                not isinstance(coords, list)
                or len(coords) < 2
                or geometry.get("type") != "Point"
            ):
                continue

            lon, lat = coords[0], coords[1]
            depth_km = coords[2] if len(coords) >= 3 else None

            mag = properties.get("mag")
            place = properties.get("place")
            time_ms = properties.get("time")
            usgs_id = feature.get("id")

            # Validate coordinates
            if not isinstance(lon, (int, float)) or abs(lon) > 180:
                continue
            if not isinstance(lat, (int, float)) or abs(lat) > 90:
                continue
            if depth_km is not None and not isinstance(depth_km, (int, float)):
                depth_km = None
            if mag is None or not isinstance(mag, (int, float)) or mag > 10:
                continue
            # M2.5+ minimum (matches God's View behavior)
            if mag < 2.5:
                continue

            # Stable ID
            stable_id = str(usgs_id) if usgs_id else f"event-{index + 1}"
            if stable_id in seen_ids:
                continue
            seen_ids.add(stable_id)

            rows.append(
                {
                    "id": stable_id,
                    "usgs_id": usgs_id,
                    "lon": lon,
                    "lat": lat,
                    "depth_km": depth_km,
                    "mag": mag,
                    "place": str(place) if place else None,
                    "time_ms": time_ms if isinstance(time_ms, (int, float)) else None,
                }
            )
        except Exception:
            # Skip individual malformed features but keep processing
            continue

    return rows


def _filter_by_area(rows, area):
    """Filter earthquake rows by an area constraint.

    area supports exactly one of:
    - place: substring match against place name
    - bbox: [west, south, east, north] — inclusive bounds
    - lat + lon + optional radius_km: great-circle distance filter
    """
    if not area or not isinstance(area, dict):
        return rows

    place = area.get("place")
    bbox = area.get("bbox")
    lat = area.get("lat")
    lon = area.get("lon")
    radius_km = area.get("radius_km")

    specified = sum(
        1
        for v in (place, bbox, lat, lon)
        if v is not None
    )
    if specified == 0:
        return rows
    if specified > 2 or (place and bbox) or (place and (lat or lon)) or (bbox and (lat or lon)):
        raise ValueError(
            "area must specify exactly one of: place, bbox, or lat+lon"
        )

    if place is not None:
        needle = str(place).strip().lower()
        if not needle:
            raise ValueError("area.place must be a non-empty string")
        return [r for r in rows if r.get("place") and needle in r["place"].lower()]

    if bbox is not None:
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(v, (int, float)) for v in bbox)
        ):
            raise ValueError("area.bbox must be [west, south, east, north]")
        west, south, east, north = bbox
        return [
            r
            for r in rows
            if west <= r["lon"] <= east and south <= r["lat"] <= north
        ]

    # lat + lon (+ optional radius_km)
    if lat is None or lon is None:
        raise ValueError("area requires both lat and lon when not using place/bbox")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise ValueError("area.lat and area.lon must be numbers")
    if abs(lat) > 90 or abs(lon) > 180:
        raise ValueError("area.lat must be [-90, 90], area.lon must be [-180, 180]")

    radius_km = float(radius_km) if radius_km is not None else 2000.0
    if radius_km < 0.1 or radius_km > 2000:
        raise ValueError("area.radius_km must be between 0.1 and 2000")

    return [r for r in rows if _haversine_km(lat, lon, r["lat"], r["lon"]) <= radius_km]


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def earthquakes(parameters: dict, player=None, session_memory=None) -> str:
    """JARVIS action for recent earthquake data from the USGS feed.

    Actions:
    - "query": Fetch earthquakes matching filters (default action)
    - "info": Return tool schema/description

    Parameters:
    - action: "query" or "info"
    - area: {place: str} | {bbox: [w,s,e,n]} | {lat, lon, radius_km?}
    - min_magnitude: number (default 2.5, max 10)
    - limit: integer (default 25, max 200)
    """
    try:
        action = parameters.get("action", "query")

        if action == "info":
            return json.dumps(
                {
                    "status": "done",
                    "tool": "get_earthquakes",
                    "title": "Recent earthquakes",
                    "description": (
                        "Earthquakes of magnitude 2.5 or more from the USGS feed "
                        "for the last 24 hours, strongest first. Optionally limited "
                        "to an area and a minimum magnitude."
                    ),
                    "parameters": {
                        "area": {
                            "type": "object",
                            "description": "Where to look. Give exactly one of: "
                            "place (name such as 'Taiwan' or 'San Francisco Bay'), "
                            "bbox ([west, south, east, north] in degrees), or "
                            "lat and lon with radius_km.",
                            "properties": {
                                "place": {"type": "string", "minLength": 1, "maxLength": 200},
                                "bbox": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 4,
                                    "maxItems": 4,
                                },
                                "lat": {"type": "number", "minimum": -90, "maximum": 90},
                                "lon": {"type": "number", "minimum": -180, "maximum": 180},
                                "radius_km": {
                                    "type": "number",
                                    "minimum": 0.1,
                                    "maximum": 2000,
                                },
                            },
                        },
                        "min_magnitude": {
                            "type": "number",
                            "minimum": 2.5,
                            "maximum": 10,
                            "description": "Minimum magnitude (default 2.5)",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 200,
                            "description": "Most rows to return (default 25)",
                        },
                    },
                },
                ensure_ascii=False,
            )

        if action != "query":
            raise ValueError("action must be 'query' or 'info'")

        # Parse parameters
        area = parameters.get("area")
        min_magnitude = parameters.get("min_magnitude", 2.5)
        limit = parameters.get("limit", 25)

        # Validate min_magnitude
        try:
            min_magnitude = float(min_magnitude)
        except (TypeError, ValueError):
            raise ValueError("min_magnitude must be a number")
        if min_magnitude < 2.5 or min_magnitude > 10:
            raise ValueError("min_magnitude must be between 2.5 and 10")

        # Validate limit
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer")
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")

        # Fetch USGS data
        try:
            geojson = _usgs_fetch()
        except (URLError, HTTPError, ValueError, OSError) as exc:
            return outcome.failed(
                "earthquakes",
                f"Could not reach USGS feed: {exc}",
                hint="Check network connectivity; USGS feed may be temporarily unavailable",
            )

        # Normalize and filter
        rows = _normalize_snapshot(geojson)

        # Apply min magnitude filter (already done in normalization but
        # re-apply for the user-specified threshold)
        rows = [r for r in rows if r["mag"] >= min_magnitude]

        # Apply area filter
        try:
            rows = _filter_by_area(rows, area)
        except ValueError as exc:
            return outcome.failed("earthquakes", str(exc))

        # Sort by magnitude descending (strongest first)
        rows.sort(key=lambda r: r["mag"], reverse=True)

        # Apply limit
        rows = rows[:limit]

        # Determine freshness: USGS all_day feed is current within ~minutes
        # Mark results as fresh (not stale/fallback) since we fetched live data
        count = len(rows)

        if player:
            try:
                player.write_log(
                    f"[Earthquakes] {count} events M{min_magnitude}+ "
                    f"from USGS feed"
                )
            except Exception:
                pass

        return json.dumps(
            {
                "status": "done",
                "tool": "get_earthquakes",
                "count": count,
                "min_magnitude": min_magnitude,
                "source": "USGS all_day feed",
                "fresh": True,
                "stale": False,
                "fallback": False,
                "earthquakes": rows,
            },
            ensure_ascii=False,
        )

    except (ValueError, KeyError, TypeError, URLError, HTTPError, OSError) as exc:
        return outcome.failed("earthquakes", str(exc))


TOOL = {
    "name": "earthquakes",
    "description": (
        "Fetch recent earthquakes (M2.5+) from the USGS all-day feed, "
        "strongest first. Optionally filter by area (place name, bounding box, "
        "or lat/lon with radius) and minimum magnitude. Returns structured "
        "earthquake records with id, magnitude, depth, location, and time."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["query", "info"],
                "description": "'query' to fetch data, 'info' for schema",
            },
            "area": {
                "type": "OBJECT",
                "description": "Where to look: exactly one of place, bbox, or lat+lon",
                "properties": {
                    "place": {
                        "type": "STRING",
                        "description": "Place name (e.g. 'Taiwan', 'San Francisco Bay')",
                        "minLength": 1,
                        "maxLength": 200,
                    },
                    "bbox": {
                        "type": "ARRAY",
                        "items": {"type": "NUMBER"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "[west, south, east, north] in degrees",
                    },
                    "lat": {
                        "type": "NUMBER",
                        "minimum": -90,
                        "maximum": 90,
                        "description": "Latitude center point",
                    },
                    "lon": {
                        "type": "NUMBER",
                        "minimum": -180,
                        "maximum": 180,
                        "description": "Longitude center point",
                    },
                    "radius_km": {
                        "type": "NUMBER",
                        "minimum": 0.1,
                        "maximum": 2000,
                        "description": "Search radius in km (default 2000)",
                    },
                },
            },
            "min_magnitude": {
                "type": "NUMBER",
                "minimum": 2.5,
                "maximum": 10,
                "description": "Minimum magnitude (default 2.5)",
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
    "handler": earthquakes,
}