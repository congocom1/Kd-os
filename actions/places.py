"""JARVIS action for place search using Google Places.

Port of the God's Eye View search_places tool. Finds businesses, landmarks and
other points of interest matching a query within an area, using Google Places.

Note: Requires a Google Places API key configured for the server. Without one,
reports that the data source is unavailable.

Parameters:
- query: search query string (required)
- area: object with exactly one of place, bbox, or lat+lon (required)
- limit: max results (default 5, max 20)
"""

import json
import math
import os
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
from pathlib import Path
import logging
logger = logging.getLogger(__name__)

from core import outcome

GOOGLE_PLACES_BASE = "https://places.googleapis.com/v1/places:searchText"
MAX_SEARCH_RADIUS_M = 50_000
SEARCH_RESULTS = 5

from config.secrets import get_secret


def _get_api_key():
    """Resolve the Google Places API key via central secrets loader."""
    return get_secret("google_places_api_key")


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


def _filter_by_area(rows, area):
    """Filter place rows by an area constraint."""
    if not area or not isinstance(area, dict):
        return rows

    place = area.get("place")
    bbox = area.get("bbox")
    lat = area.get("lat")
    lon = area.get("lon")
    radius_km = area.get("radius_km")

    specified = sum(1 for v in (place, bbox, lat, lon) if v is not None)
    if specified == 0:
        return rows
    if specified > 2 or (place and bbox) or (place and (lat or lon)) or (bbox and (lat or lon)):
        raise ValueError("area must specify exactly one of: place, bbox, or lat+lon")

    if place is not None:
        needle = str(place).strip().lower()
        if not needle:
            raise ValueError("area.place must be a non-empty string")
        return [r for r in rows if r.get("place") and needle in str(r["place"]).lower()]

    if bbox is not None:
        if (
            not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(v, (int, float)) for v in bbox)
        ):
            raise ValueError("area.bbox must be [west, south, east, north]")
        west, south, east, north = bbox
        return [r for r in rows if west <= r["lon"] <= east and south <= r["lat"] <= north]

    if lat is None or lon is None:
        raise ValueError("area requires both lat and lon when not using place/bbox")
    radius_km = float(radius_km) if radius_km is not None else 2000.0
    if radius_km < 0.1 or radius_km > 2000:
        raise ValueError("area.radius_km must be between 0.1 and 2000")
    return [r for r in rows if _haversine_km(lat, lon, r["lat"], r["lon"]) <= radius_km]


def places(parameters: dict, player=None, session_memory=None) -> str:
    """JARVIS action for place search using Google Places.

    Parameters:
    - action: "query" (default) or "info"
    - query: search query string (required for query)
    - area: {place: str} | {bbox: [w,s,e,n]} | {lat, lon, radius_km?} (required for query)
    - limit: max results (default 5, max 20)
    """
    try:
        action = parameters.get("action", "query")

        if action == "info":
            return json.dumps(
                {
                    "status": "done",
                    "tool": "search_places",
                    "title": "Search places",
                    "description": (
                        "Find businesses, landmarks and other points of interest "
                        "matching a query within an area, using Google Places."
                    ),
                    "parameters": {
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                            "description": "Search query (e.g. 'coffee shop', 'museum')",
                        },
                        "area": {
                            "type": "object",
                            "description": "Where to look: exactly one of place, "
                            "bbox ([west, south, east, north]), or lat+lon+radius_km",
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
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "description": "Most rows to return (default 5)",
                        },
                    },
                    "key_required": not bool(_get_api_key()),
                },
                ensure_ascii=False,
            )

        if action != "query":
            return outcome.failed("places", "action must be 'query' or 'info'")

        query = parameters.get("query", "").strip()
        if not query:
            return outcome.failed("places", "query is required for query action")

        area = parameters.get("area")
        if not area or not isinstance(area, dict):
            return outcome.failed("places", "area is required for query action")

        limit = parameters.get("limit", SEARCH_RESULTS)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return outcome.failed("places", "limit must be an integer")
        if limit < 1 or limit > 20:
            return outcome.failed("places", "limit must be between 1 and 20")

        api_key = _get_api_key()
        if not api_key:
            return outcome.failed(
                "places",
                "Place search needs a Google Places key configured for this server",
                hint="Set GOOGLE_PLACES_API_KEY environment variable",
            )

        # Resolve area to center point and radius
        center_lat, center_lon = None, None
        radius_km = 5.0  # default 5 km radius

        place_name = area.get("place")
        bbox = area.get("bbox")
        lat = area.get("lat")
        lon = area.get("lon")
        area_radius = area.get("radius_km")

        if place_name:
            # Geocode the place name using Google Places Text Search first
            geocode_url = GOOGLE_PLACES_BASE + "?" + urlencode({
                "query": place_name,
                "key": api_key,
            })
            try:
                req = Request(geocode_url, headers={"User-Agent": "JARVIS/1.0"})
                with urlopen(req, timeout=15) as resp:
                    if resp.status != 200:
                        raise ValueError(f"Google Places geocode returned HTTP {resp.status}")
                    geo_data = json.loads(resp.read().decode("utf-8"))
                places_list = geo_data.get("places", [])
                if not places_list:
                    return outcome.failed("places", f"Could not geocode place: {place_name}")
                first = places_list[0]
                location = first.get("location", {})
                center_lat = float(location.get("latitude", 0))
                center_lon = float(location.get("longitude", 0))
            except (URLError, HTTPError, ValueError, OSError) as exc:
                return outcome.failed("places", f"Could not geocode place: {exc}")
        elif bbox:
            west, south, east, north = bbox
            center_lat = (south + north) / 2
            center_lon = (west + east) / 2
            radius_km = max(_haversine_km(center_lat, center_lon, north, east),
                           _haversine_km(center_lat, center_lon, south, west))
        elif lat is not None and lon is not None:
            center_lat = float(lat)
            center_lon = float(lon)
            radius_km = float(area_radius) if area_radius is not None else 5.0
        else:
            return outcome.failed("places", "area must specify place, bbox, or lat+lon")

        radius_m = min(MAX_SEARCH_RADIUS_M, max(500, int(radius_km * 1000)))

        # Call Google Places Text Search
        body = {
            "textQuery": query,
            "locationBias": {
                "circle": {
                    "center": {"latitude": center_lat, "longitude": center_lon},
                    "radius": float(radius_m),
                }
            },
            "pageSize": min(limit, 10),
        }
        req = Request(
            GOOGLE_PLACES_BASE,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.primaryType,places.location,places.distanceMeters",
                "User-Agent": "JARVIS/1.0",
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    raise ValueError(f"Google Places search returned HTTP {resp.status}")
                result = json.loads(resp.read().decode("utf-8"))
        except (URLError, HTTPError, ValueError, OSError) as exc:
            return outcome.failed(
                "places",
                f"Could not reach Google Places: {exc}",
                hint="Check network connectivity and API key",
            )

        raw_places = result.get("places", []) or []
        rows = []
        for p in raw_places:
            loc = p.get("location", {})
            rows.append({
                "id": p.get("id"),
                "name": (p.get("displayName") or {}).get("text"),
                "address": p.get("formattedAddress"),
                "type": p.get("primaryType"),
                "lat": round(float(loc.get("latitude", 0)), 6) if loc.get("latitude") else None,
                "lon": round(float(loc.get("longitude", 0)), 6) if loc.get("longitude") else None,
                "distance_m": p.get("distanceMeters"),
            })

        # Filter by area
        try:
            rows = _filter_by_area(rows, area)
        except ValueError as exc:
            return outcome.failed("places", str(exc))

        # Apply limit
        rows = rows[:limit]

        count = len(rows)

        if player:
            try:
                player.write_log(f"[Places] {count} places matching '{query}'")
            except Exception:
                pass

        limited = len(raw_places) >= SEARCH_RESULTS
        narrowed = radius_km * 1000 > MAX_SEARCH_RADIUS_M
        notes = []
        if limited:
            notes.append(f"the search returns at most {SEARCH_RESULTS} matches")
        if narrowed:
            notes.append(f"searched within {MAX_SEARCH_RADIUS_M / 1000} km of center")

        return json.dumps(
            {
                "status": "done",
                "tool": "search_places",
                "count": count,
                "query": query,
                "source": "Google Places",
                "places": rows,
                "may_have_more": limited or narrowed,
                "searched_radius_km": radius_m / 1000,
                "summary": (
                    f"{count} place(s) matching \"{query}\""
                    + (f" ({'; '.join(notes)})." if notes else ".")
                ),
            },
            ensure_ascii=False,
        )

    except (URLError, HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
        return outcome.failed("places", str(exc))


TOOL = {
    "name": "places",
    "description": (
        "Find businesses, landmarks and other points of interest matching a "
        "query within an area, using Google Places. Requires a Google Places "
        "API key configured for this server."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["query", "info"],
                "description": "'query' to fetch data, 'info' for schema",
            },
            "query": {
                "type": "STRING",
                "description": "Search query (e.g. 'coffee shop', 'museum')",
                "minLength": 1,
                "maxLength": 200,
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
                        "description": "Search radius in km",
                    },
                },
            },
            "limit": {
                "type": "INTEGER",
                "minimum": 1,
                "maximum": 20,
                "description": "Maximum results (default 5)",
            },
        },
        "required": [],
    },
    "handler": places,
}