"""Voice and keyboard integration for God's Eye View globe queries.

Provides natural-language voice command patterns that map to globe actions,
and keyboard shortcut definitions for quick globe access.

Voice commands are matched against transcripts from the wake-word/voice
session. When a match is found, the corresponding globe action is invoked
through the registered action handler (earthquakes, fires, weather, launches,
places, or globe itself).

Keyboard shortcuts are defined as (chord, description, action_params) tuples
that can be registered with the Qt hotkey system in main.py.
"""

import re
import json
from typing import Optional, Tuple, List, Dict, Any

# ── Voice command patterns ──────────────────────────────────────────────────

# Each pattern: (regex, action_name, param_extractor)
# param_extractor receives match groups and returns a dict of action parameters
VOICE_PATTERNS: List[Tuple[str, str, callable]] = [
    # Earthquakes
    (
        r"(?i)(?:show|find|get|list)\s+(?:recent\s+)?earthquakes?(?:\s+(?:near|in|around|of)\s+(?P<place>.+?))?(?:\s+(?:magnitude\s+)?(?:of\s+)?(?P<mag>\d+(?:\.\d+)?)\s*(?:or\s+)?(?:higher|above|min))?\.?$",
        "earthquakes",
        lambda m: _eq_params(m),
    ),
    (
        r"(?i)(?P<mag>\d+(?:\.\d+)?)\s*(?:or\s+)?(?:higher|above|min)\s+(?:magnitude\s+)?earthquakes?\.?$",
        "earthquakes",
        lambda m: {"min_magnitude": float(m.group("mag"))},
    ),
    # Fires
    (
        r"(?i)(?:show|find|get|list)\s+(?:active\s+)?fires?(?:\s+(?:near|in|around|of)\s+(?P<place>.+?))?\.?$",
        "fires",
        lambda m: _area_params(m),
    ),
    # Weather
    (
        r"(?i)(?:what'?s\s+the\s+)?weather(?:\s+(?:at|in|for)\s+(?P<place>.+?))?\.?$",
        "weather",
        lambda m: _weather_params(m),
    ),
    # Launches
    (
        r"(?i)(?:show|find|get|list)\s+(?:recent\s+)?(?:orbital\s+)?(?:launches|rocket\s+launches|space\s+launches)\.?$",
        "launches",
        lambda m: {},
    ),
    # Places
    (
        r"(?i)(?:find|search)\s+(?P<query>.+?)(?:\s+(?:near|in|around|of)\s+(?P<place>.+?))?\.?$",
        "places",
        lambda m: _places_params(m),
    ),
    # Globe status/health
    (
        r"(?i)(?:globe|god.?s\s+eye)\s+(?:status|health|is\s+it\s+(?:up|running|online))\.?$",
        "globe",
        lambda m: {"action": "health"},
    ),
    # Globe open
    (
        r"(?i)(?:open|show)\s+(?:the\s+)?globe\.?$",
        "globe",
        lambda m: {"action": "open"},
    ),
]


def _eq_params(m) -> Dict[str, Any]:
    """Extract earthquake parameters from a voice match."""
    params: Dict[str, Any] = {"action": "query"}
    if m.group("place"):
        params["area"] = {"place": m.group("place").strip()}
    if m.group("mag"):
        params["min_magnitude"] = float(m.group("mag"))
    return params


def _area_params(m) -> Dict[str, Any]:
    """Extract area parameters from a voice match."""
    params: Dict[str, Any] = {"action": "query"}
    if m.group("place"):
        params["area"] = {"place": m.group("place").strip()}
    return params


def _weather_params(m) -> Dict[str, Any]:
    """Extract weather parameters from a voice match."""
    params: Dict[str, Any] = {"action": "query"}
    if m.group("place"):
        # Try to geocode later; for now pass place as a hint
        params["location"] = {"lat": 0, "lon": 0}  # placeholder, resolved downstream
        params["_place_hint"] = m.group("place").strip()
    return params


def _places_params(m) -> Dict[str, Any]:
    """Extract places parameters from a voice match."""
    params: Dict[str, Any] = {"action": "query", "query": m.group("query").strip()}
    if m.group("place"):
        params["area"] = {"place": m.group("place").strip()}
    return params


def match_voice_command(transcript: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Match a voice transcript against known globe command patterns.

    Returns (action_name, parameters) on match, or None if no pattern matches.
    """
    transcript = transcript.strip()
    if not transcript:
        return None

    for pattern, action_name, extractor in VOICE_PATTERNS:
        m = re.search(pattern, transcript)
        if m:
            try:
                params = extractor(m)
                return (action_name, params)
            except Exception:
                # Pattern matched but extraction failed — skip
                continue

    return None


# ── Keyboard shortcuts ──────────────────────────────────────────────────────

# Each shortcut: (chord, display_name, action_call)
# chord is a tuple like ("ctrl", "shift", "e") for Qt key sequences
# action_call is a dict of parameters passed to the globe action
KEYBOARD_SHORTCUTS: List[Tuple[Tuple[str, ...], str, Dict[str, Any]]] = [
    (("ctrl", "shift", "e"), "Show recent earthquakes",
     {"action": "query", "min_magnitude": 2.5, "limit": 10}),
    (("ctrl", "shift", "f"), "Show active fires",
     {"action": "query", "limit": 10}),
    (("ctrl", "shift", "w"), "Show current weather",
     {"action": "query"}),
    (("ctrl", "shift", "l"), "Show recent launches",
     {"action": "query", "limit": 10}),
    (("ctrl", "shift", "g"), "Globe server health",
     {"action": "health"}),
    (("ctrl", "shift", "o"), "Open God's Eye View",
     {"action": "open"}),
]


def get_keyboard_shortcuts() -> List[Dict[str, Any]]:
    """Return keyboard shortcut definitions for the UI.

    Returns a list of dicts with keys: chord, label, action.
    """
    shortcuts = []
    for chord, label, action in KEYBOARD_SHORTCUTS:
        shortcuts.append({
            "chord": "+".join(chord),
            "label": label,
            "action": action,
        })
    return shortcuts


def execute_shortcut(action: Dict[str, Any], action_registry) -> str:
    """Execute a keyboard shortcut action through the action registry.

    action_registry should have a `run(name, parameters)` method that dispatches
    to the registered action handler.
    """
    name = action.pop("_action_name", None) or "globe"
    # The action dict contains the parameters for the specific tool
    # Determine which tool based on the action contents
    if "min_magnitude" in action or ("area" in action and action.get("action") == "query"):
        name = "earthquakes"
    elif "area" in action and "frp" not in str(action):
        name = "fires"
    elif "location" in action or "_place_hint" in action:
        name = "weather"
    elif "query" in action and "area" in action:
        name = "places"
    elif "action" in action and action["action"] in ("health", "open"):
        name = "globe"
    elif action.get("action") == "query":
        name = "launches"

    return action_registry.run(name, action)