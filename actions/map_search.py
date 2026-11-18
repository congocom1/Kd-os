# map_search.py
# Map and place search for JARVIS — opens Google Maps for a query.
#
# Auto-discovered by core/action_loader via the TOOL dict below.

from __future__ import annotations

import sys
import urllib.parse
import webbrowser
from pathlib import Path

from core import outcome


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _maps_url(query: str) -> str:
    """Build a Google Maps search URL for the given query."""
    encoded = urllib.parse.quote_plus(query.strip())
    return f"https://www.google.com/maps/search/{encoded}"


def _search_places(query: str) -> str:
    """Open the map URL in the browser and return a result string."""
    url = _maps_url(query)
    try:
        opened = webbrowser.open(url)
    except Exception as e:
        return outcome.failed(
            "map_search", f"could not open browser: {e}", query=query
        )
    if not opened:
        return outcome.unverified(
            "map_search",
            "browser open returned False — the map URL may still have launched",
            query=query,
            url=url,
        )
    return outcome.done(
        "map_search",
        query=query,
        url=url,
        opened=True,
    )


def map_search(parameters: dict, player=None, session_memory=None) -> str:
    """Search for a place on Google Maps and open it in the browser.

    Parameters:
        query:        Place, address, or business to search for (required)
        open_browser: Whether to open the map URL in the default browser (default: true)
    """
    query = parameters.get("query", "").strip()
    if not query:
        return outcome.failed(
            "map_search", "no query provided — say what place or address to find"
        )

    open_browser = parameters.get("open_browser", True)
    if open_browser is not False:
        return _search_places(query)

    url = _maps_url(query)
    return outcome.done(
        "map_search",
        query=query,
        url=url,
        opened=False,
    )


# ── Tool declaration (auto-discovered by core/action_loader.py) ───────────────

TOOL = {
    "name": "map_search",
    "description": (
        "Search for a place, address, or business on Google Maps and open it "
        "in the default web browser. Use when the user asks to find a location, "
        "get directions, look up a business, or see a place on a map."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Place, address, business name, or location to search for",
            },
            "open_browser": {
                "type": "BOOLEAN",
                "description": "Open the map URL in the browser (default: true)",
            },
        },
        "required": ["query"],
    },
    "handler": map_search,
}
