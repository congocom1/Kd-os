"""Resolve secrets from the environment or the local JSON config."""

from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from core.metrics import increment, record_timing

_CONFIG_PATH = Path(__file__).resolve().parent / "api_keys.json"

# Logical names map to the environment variable and its JSON equivalent.
_SECRET_MAP = {
    "firms_map_key": ("FIRMS_MAP_KEY", "firms_map_key"),
    "google_places_api_key": ("GOOGLE_PLACES_API_KEY", "google_places_api_key"),
    "gemini_api_key": ("GEMINI_API_KEY", "gemini_api_key"),
}


@lru_cache(maxsize=1)
def _read_config(path: Path, _revision: tuple[int, ...]) -> dict[str, Any]:
    """Reuse the parsed object until the file changes; don't cache I/O errors."""
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_config() -> dict[str, Any]:
    try:
        st = _CONFIG_PATH.stat()
        # Inode and device catch atomic replacement even with identical sizes
        # and preserved modification times. ctime catches in-place edits.
        return _read_config(_CONFIG_PATH, (st.st_dev, st.st_ino, st.st_size,
                                           st.st_mtime_ns, st.st_ctime_ns))
    except OSError:
        return {}


def get_secret(name: str) -> str:
    """Return an environment override, a configured string, or an empty string."""
    increment("get_secret.call")
    start = perf_counter()
    try:
        mapping = _SECRET_MAP.get(name)
        if mapping is None:
            return ""
        env_name, config_key = mapping
        override = os.environ.get(env_name)
        if override:
            return override
        value = _load_config().get(config_key)
        return value if isinstance(value, str) else ""
    finally:
        record_timing("get_secret.time", perf_counter() - start)
