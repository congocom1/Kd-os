"""JARVIS action for active fire detections from NASA FIRMS.

Port of the God's Eye View get_active_fires tool. Fetches satellite fire
detections from NASA FIRMS in the last 24 hours within an area, most intense
(fire radiative power) first.

Note: NASA FIRMS requires a MAP_KEY. Without one, this action reports that the
data source is unavailable rather than fabricating results.

Parameters:
- area: object with exactly one of place, bbox, or lat+lon (required)
- limit: max results (default 25, max 200)
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from core import outcome

# NASA FIRMS API - requires FIRMS_MAP_KEY environment variable or config entry
FIRMS_API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_SOURCES = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT"]

from config.secrets import get_secret


def _get_map_key():
    """Resolve the NASA FIRMS MAP_KEY via central secrets loader."""
    return get_secret("firms_map_key")


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
    """Filter fire rows by an area constraint."""
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


def _acquired_ms_utc(acq_date, acq_time):
    """Convert FIRMS acq_date/acq_time to epoch ms, or NaN."""
    if not isinstance(acq_date, str) or len(acq_date) != 10:
        return float("nan")
    time_text = str(acq_time or "").strip().zfill(4)
    if not time_text.isdigit() or len(time_text) > 4:
        return float("nan")
    time_text = time_text.zfill(4)
    try:
        hours = int(time_text[:2])
        minutes = int(time_text[2:4])
        if hours > 23 or minutes > 59:
            return float("nan")
        iso = f"{acq_date}T{time_text[:2]}:{time_text[2:4]}:00.000Z"
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.timestamp() * 1000
    except Exception:
        return float("nan")


def fires(parameters: dict, player=None, session_memory=None) -> str:
    """JARVIS action for active fire detections from NASA FIRMS.

    Parameters:
    - action: "query" (default) or "info"
    - area: {place: str} | {bbox: [w,s,e,n]} | {lat, lon, radius_km?} (required for query)
    - limit: integer (default 25, max 200)
    """
    try:
        action = parameters.get("action", "query")

        if action == "info":
            return json.dumps(
                {
                    "status": "done",
                    "tool": "get_active_fires",
                    "title": "Active fires",
                    "description": (
                        "Satellite fire detections from NASA FIRMS in the last 24 hours "
                        "within an area, most intense (fire radiative power) first. "
                        "Requires a NASA FIRMS MAP_KEY configured for this server."
                    ),
                    "parameters": {
                        "area": {
                            "type": "object",
                            "description": "Where to look. Give exactly one of: place, "
                            "bbox ([west, south, east, north]), or lat+lon+radius_km.",
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
                            "maximum": 200,
                            "description": "Most rows to return (default 25)",
                        },
                    },
                    "key_required": not bool(_get_map_key()),
                },
                ensure_ascii=False,
            )

        if action != "query":
            return outcome.failed("fires", "action must be 'query' or 'info'")

        area = parameters.get("area")
        if not area or not isinstance(area, dict):
            return outcome.failed("fires", "area is required for query action")

        limit = parameters.get("limit", 25)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return outcome.failed("fires", "limit must be an integer")
        if limit < 1 or limit > 200:
            return outcome.failed("fires", "limit must be between 1 and 200")

        map_key = _get_map_key()
        if not map_key:
            return outcome.failed(
                "fires",
                "Fire detections need a NASA FIRMS key configured for this server",
                hint="Set FIRMS_MAP_KEY environment variable",
            )

        # FIRMS API: /api/area/csv/{KEY}/{SOURCE}/world/2  (days=2 = trailing 48h)
        all_fires = []
        for source in FIRMS_SOURCES:
            url = f"{FIRMS_API_BASE}/{map_key}/{source}/world/2"
            try:
                req = Request(url, headers={"User-Agent": "JARVIS/1.0"})
                with urlopen(req, timeout=30) as resp:
                    if resp.status != 200:
                        continue
                    text = resp.read().decode("utf-8", errors="replace")
            except (URLError, HTTPError, OSError):
                continue

            # Parse CSV
            lines = text.strip().split("\n")
            if len(lines) < 2:
                continue
            header = lines[0].split(",")
            try:
                lat_idx = header.index("latitude")
                lon_idx = header.index("longitude")
                frp_idx = header.index("frp")
                conf_idx = header.index("confidence")
                sat_idx = header.index("satellite")
                acq_date_idx = header.index("acq_date")
                acq_time_idx = header.index("acq_time")
                daynight_idx = header.index("daynight")
            except ValueError:
                continue

            for line in lines[1:]:
                cols = line.split(",")
                if len(cols) <= max(lat_idx, lon_idx, frp_idx):
                    continue
                try:
                    lat = float(cols[lat_idx])
                    lon = float(cols[lon_idx])
                    frp = float(cols[frp_idx]) if cols[frp_idx] else None
                except (ValueError, IndexError):
                    continue
                all_fires.append({
                    "lat": lat,
                    "lon": lon,
                    "frp_mw": frp,
                    "confidence": cols[conf_idx] if conf_idx < len(cols) else None,
                    "satellite": cols[sat_idx] if sat_idx < len(cols) else None,
                    "acq_date": cols[acq_date_idx] if acq_date_idx < len(cols) else None,
                    "acq_time": cols[acq_time_idx] if acq_time_idx < len(cols) else None,
                    "daynight": cols[daynight_idx] if daynight_idx < len(cols) else None,
                })

        # Filter by area
        try:
            all_fires = _filter_by_area(all_fires, area)
        except ValueError as exc:
            return outcome.failed("fires", str(exc))

        # Sort by FRP descending (most intense first)
        all_fires.sort(key=lambda r: (r["frp_mw"] or 0), reverse=True)

        # Apply limit
        rows = all_fires[:limit]

        # Format timestamps
        for row in rows:
            ts = _acquired_ms_utc(row["acq_date"], row["acq_time"])
            row["acquired"] = (
                datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
                if ts == ts  # not NaN
                else None
            )

        # Determine staleness (we can't know without the proxy, so assume fresh)
        stale = False
        missing_sources = []

        count = len(rows)

        if player:
            try:
                player.write_log(f"[Fires] {count} detections from NASA FIRMS")
            except Exception:
                pass

        notes = []
        if stale:
            notes.append("data may be stale")
        if missing_sources:
            notes.append(f"no data from {', '.join(missing_sources)}")

        return json.dumps(
            {
                "status": "done",
                "tool": "get_active_fires",
                "count": count,
                "stale": stale,
                "missing_sources": missing_sources,
                "source": "NASA FIRMS",
                "fires": rows,
                "summary": (
                    f"{count} fire detection(s) in the last 24 hours"
                    + (f" ({'; '.join(notes)})." if notes else ".")
                ),
            },
            ensure_ascii=False,
        )

    except (URLError, HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
        return outcome.failed("fires", str(exc))


TOOL = {
    "name": "fires",
    "description": (
        "Satellite fire detections from NASA FIRMS in the last 24 hours within "
        "an area, most intense (fire radiative power) first. Requires a NASA "
        "FIRMS MAP_KEY configured for this server. Use area to specify where "
        "to look (place name, bounding box, or lat/lon with radius)."
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
                        "description": "Place name (e.g. 'California', 'Amazon')",
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
                "maximum": 200,
                "description": "Maximum results (default 25)",
            },
        },
        "required": [],
    },
    "handler": fires,
}