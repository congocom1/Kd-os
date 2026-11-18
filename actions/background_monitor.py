"""
BackgroundMonitor — user-configured topic watching.
Checks DDG news once per day per topic; alerts JARVIS when a new headline appears.
No crypto, no finance, no uninvited tracking.
"""
import functools
import hashlib
import logging
import re
import time
from datetime import datetime

from core.metrics import increment, record_timing

logger = logging.getLogger(__name__)


# ── Blocked categories (never monitor regardless of what user says) ────────────

_BLOCKED = {
    # Brand / asset names — spelled the same in every language
    "bitcoin", "ethereum", "dogecoin", "solana", "binance",
    "nft", "blockchain", "defi", "altcoin", "memecoin", "coin", "token",
    # spellings of the "crypto" root across different languages
    "crypto", "kripto", "cripto", "krypto", "крипто", "仮想通貨", "暗号資産",
    "cryptocurrency",
}


def _is_blocked(topic: str) -> bool:
    """Return whether a topic belongs to a blocked category."""
    text = topic.lower()
    return any(word in text for word in _BLOCKED)


# ── Slug / hash helpers ────────────────────────────────────────────────────────


def _slug(topic: str) -> str:
    """Convert a topic into a stable storage key."""
    return re.sub(r"[^a-z0-9]+", "_", topic.lower().strip())[:40].strip("_")


def _title_hash(title: str) -> str:
    """Return a compact hash for a headline."""
    return hashlib.md5(title.encode("utf-8", errors="ignore")).hexdigest()[:12]


# ── Memory I/O ─────────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=32)
def _load() -> dict:
    """Load monitored topics from memory manager."""
    increment("monitor.load.call")
    start = time.time()
    from memory.memory_manager import load_memory

    data = load_memory().get("monitors", {})
    result = data if isinstance(data, dict) else {}
    record_timing("monitor.load.time", time.time() - start)
    return result


def _save(monitors: dict) -> None:
    """Persist monitored topics through the memory manager's atomic writer."""
    from memory.memory_manager import load_memory, save_memory

    memory = load_memory()
    memory["monitors"] = monitors
    save_memory(memory)


# ── Public API ─────────────────────────────────────────────────────────────────


def add_monitor(topic: str) -> str:
    """Add a topic to the monitoring list.

    JARVIS will check for new headlines on this topic once per day.
    Crypto and financial topics are automatically blocked.

    Args:
        topic: The topic to monitor (e.g., "space news", "tech updates").

    Returns:
        Status message indicating success or reason for failure.
    """
    logger.info("Attempting to add monitor for topic: %r", topic)
    topic = topic.strip()
    if not topic:
        return "Please specify a topic to monitor."
    if _is_blocked(topic):
        return "I don't monitor crypto or financial topics."
    monitors = _load()
    slug = _slug(topic)
    if slug in monitors:
        return f"Already monitoring: {monitors[slug]['topic']}"
    monitors[slug] = {
        "topic": topic,
        "added": datetime.now().strftime("%Y-%m-%d"),
    }
    _save(monitors)
    return f"Now monitoring: {topic}"


def remove_monitor(topic: str) -> str:
    """Remove a topic from the monitoring list.

    Args:
        topic: The topic to stop monitoring.

    Returns:
        Status message indicating success or reason for failure.
    """
    logger.info("Attempting to remove monitor for topic: %r", topic)
    topic = topic.strip().lower()
    monitors = _load()
    slug = _slug(topic)
    if slug in monitors:
        label = monitors.pop(slug)["topic"]
        _save(monitors)
        return f"Stopped monitoring: {label}"
    for key, value in list(monitors.items()):
        if topic in value.get("topic", "").lower():
            label = monitors.pop(key)["topic"]
            _save(monitors)
            return f"Stopped monitoring: {label}"
    return f"Not found in monitored topics: {topic}"


def list_monitors() -> list[str]:
    """List all monitored topics."""
    return [value.get("topic", key) for key, value in _load().items()]


def check_all() -> list[str]:
    """Run all pending topic checks and return new-headline alerts."""
    from actions.web_search import _ddg_news

    monitors = _load()
    if not monitors:
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    alerts = []
    changed = False

    for slug, data in monitors.items():
        if data.get("last_check") == today:
            continue

        topic = data.get("topic", slug)
        try:
            results = _ddg_news(topic, max_results=5)
            if not results:
                monitors[slug]["last_check"] = today
                changed = True
                continue

            top = results[0]
            title = top.get("title", "").strip()
            if not title:
                continue

            title_hash = _title_hash(title)
            monitors[slug]["last_check"] = today
            changed = True

            if title_hash == data.get("last_hash"):
                continue

            monitors[slug]["last_hash"] = title_hash

            snippet = top.get("snippet", "")[:150]
            source = top.get("source", "")
            parts = [f"[MONITOR_ALERT] {topic}", f"Headline: {title}"]
            if snippet:
                parts.append(snippet)
            if source:
                parts.append(f"Source: {source}")
            alerts.append("\n".join(parts))
            print(f"[Monitor] 🔔 New headline for '{topic}': {title[:60]}")

        except Exception as exc:
            logger.warning("Check failed for %r: %s", topic, exc)

    if changed:
        _save(monitors)

    return alerts
