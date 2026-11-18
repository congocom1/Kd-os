"""
Centralised secret loading for Mark-LVI.

Provides get_secret(name) which resolves a secret from environment variables
first, then from config/api_keys.json. Avoids duplicated loading logic across
actions.

Environment variables take precedence over the JSON config file.
The JSON file should never be committed with real secrets.
"""

from __future__ import annotations
import functools
import json
import os
import time
from pathlib import Path
from typing import Any

from core.metrics import increment, record_timing, get_summary

# Cache get_secret for performance — environments vars are checked first, then config. LRU cache avoids repeated file reads.
_CONFIG_PATH = Path(__file__).resolve().parent / "api_keys.json"

# Mapping of logical secret names to env var names and config keys.
# Keep this as the single source of truth.
_SECRET_MAP = {
    "firms_map_key": {"env": "FIRMS_MAP_KEY", "config": "firms_map_key"},
    "google_places_api_key": {"env": "GOOGLE_PLACES_API_KEY", "config": "google_places_api_key"},
    "gemini_api_key": {"env": "GEMINI_API_KEY", "config": "gemini_api_key"},
}

# ── Tracking wrapper for get_secret ─────────────────────────────────────
def _tracked_get_secret(name: str) -> str:
    """Track get_secret calls while delegating to the cached version."""
    increment("get_secret.call")
    start = time.time()
    result = _cached_get_secret(name)
    record_timing("get_secret.time", time.time() - start)
    return result

# The actual cached function (no tracking inside, tracking done via wrapper)
@functools.lru_cache(maxsize=128)
def _cached_get_secret(name: str) -> str:
    """Return a secret value for `name`.

    Resolution order:
      1. Environment variable defined in _SECRET_MAP
      2. Value from config/api_keys.json
      3. Empty string if not found
    """
    mapping = _SECRET_MAP.get(name)
    if not mapping:
        return ""
    
    # Check environment variable first
    env_name = mapping.get("env")
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    
    # Check config file
    config_key = mapping.get("config")
    if config_key:
        config = _load_config()
        if config_key in config:
            return config[config_key]
    
    # Return empty string if not found
    return ""


def _load_config() -> dict[str, Any]:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        # Do not crash the whole app on a bad config file.
        return {}


def get_secret(name: str) -> str:
    """Return a secret value for `name`.

    Resolution order:
      1. Environment variable defined in _SECRET_MAP
      2. Value from config/api_keys.json
      3. Empty string if not found

    Tracked via _tracked_get_secret for observability.
    """
    return _tracked_get_secret(name)
