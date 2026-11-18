"""
Social Media plugin — JARVIS plugin for posting to and reading from social
platforms through the app's own config store. Pure scaffold: every action
checks whether credentials exist for that platform and, if not, tells the user
exactly what to set in ⚙ → ENGINE & PROVIDERS before it can proceed.

Supported platforms (actions take `platform`): x, youtube, instagram,
facebook, discord, telegram, reddit.

Actions:
  status         — which platforms are connected / missing credentials
  post           — post text to a platform (needs 'text', 'platform')
  get_feed       — read recent posts from a platform (needs 'platform')
  search         — search a platform (needs 'platform', 'query')
  connect        — store credentials for a platform (needs 'platform', 'token')

Credentials are stored per-platform in config under `social_media.<platform>`
and are never logged or spoken. No platform is called unless the user has
explicitly connected it.
"""

from __future__ import annotations

from memory.config_manager import get_plugin_config, save_plugin_config

PLUGIN = {
    "name": "social_media",
    "description": (
        "Post to and read from social platforms: X (Twitter), YouTube, "
        "Instagram, Facebook, Discord, Telegram, Reddit. Use 'status' to see "
        "which platforms are connected, 'connect' to add credentials for one, "
        "then 'post' / 'get_feed' / 'search'. Credentials live in your local "
        "config — nothing is sent until you connect a platform yourself."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'status', 'connect', 'post', 'get_feed', or 'search'",
            },
            "platform": {
                "type": "STRING",
                "description": "x | youtube | instagram | facebook | discord | telegram | reddit",
            },
            "text": {
                "type": "STRING",
                "description": "Text to post (for action='post')",
            },
            "query": {
                "type": "STRING",
                "description": "Search query (for action='search')",
            },
            "token": {
                "type": "STRING",
                "description": "API token/credential to store for a platform (for action='connect')",
            },
        },
        "required": ["action"],
    },
}

_PLATFORMS = (
    "x", "youtube", "instagram", "facebook", "discord", "telegram", "reddit",
)

_PLATFORM_NAMES = {
    "x": "X (Twitter)",
    "youtube": "YouTube",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "discord": "Discord",
    "telegram": "Telegram",
    "reddit": "Reddit",
}


def _verify_tokens(values: dict) -> tuple[bool, str]:
    """Test that at least one platform has a stored token."""
    found = [k for k, v in values.items() if v]
    if not found:
        return False, "No tokens stored — add one above and save."
    names = [_PLATFORM_NAMES.get(k.replace("_token", ""), k) for k in found]
    return True, f"Tokens present: {', '.join(names)}"


# ── Plugin settings (shown in ⚙ → PLUGINS → social_media) ─────────────────
PLUGIN_SETTINGS = {
    "namespace": "social_media",
    "title": "Social Media",
    "fields": [
        {
            "key": "x_token",
            "label": "X (Twitter) API token",
            "type": "password",
            "default": "",
            "placeholder": "Paste your X API token",
        },
        {
            "key": "youtube_token",
            "label": "YouTube API token",
            "type": "password",
            "default": "",
            "placeholder": "Paste your YouTube API token",
        },
        {
            "key": "instagram_token",
            "label": "Instagram API token",
            "type": "password",
            "default": "",
            "placeholder": "Paste your Instagram API token",
        },
        {
            "key": "facebook_token",
            "label": "Facebook API token",
            "type": "password",
            "default": "",
            "placeholder": "Paste your Facebook API token",
        },
        {
            "key": "discord_token",
            "label": "Discord bot token",
            "type": "password",
            "default": "",
            "placeholder": "Paste your Discord bot token",
        },
        {
            "key": "telegram_token",
            "label": "Telegram bot token",
            "type": "password",
            "default": "",
            "placeholder": "Paste your Telegram bot token",
        },
        {
            "key": "reddit_token",
            "label": "Reddit API token",
            "type": "password",
            "default": "",
            "placeholder": "Paste your Reddit API token",
        },
    ],
    "action": {
        "label": "VERIFY TOKENS",
        "run": _verify_tokens,
    },
}


def _creds(platform: str) -> dict | None:
    return get_plugin_config(f"social_media.{platform}")


def _has_creds(platform: str) -> bool:
    c = _creds(platform)
    return bool(c and c.get("token"))


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()
    if not action:
        return "Sir, please specify an action: status, connect, post, get_feed, or search."

    try:
        if action == "status":
            lines = []
            for p in _PLATFORMS:
                mark = "✓" if _has_creds(p) else "✗"
                lines.append(f"  {mark} {_PLATFORM_NAMES[p]}")
            connected = sum(1 for p in _PLATFORMS if _has_creds(p))
            return (
                f"Social media ({connected}/{len(_PLATFORMS)} connected):\n"
                + "\n".join(lines)
                + "\nUse 'connect' to add credentials for a platform."
            )

        if action == "connect":
            platform = (parameters.get("platform") or "").strip().lower()
            token = (parameters.get("token") or "").strip()
            if platform not in _PLATFORMS:
                return (f"Sir, I don't support '{platform}'. Try: "
                        + ", ".join(_PLATFORMS))
            if not token:
                return "Sir, please provide a token for that platform."
            save_plugin_config(f"social_media.{platform}", {"token": token})
            if player:
                try:
                    player.write_log(f"JARVIS: Social media connected — {_PLATFORM_NAMES[platform]}")
                except Exception:
                    pass
            return f"Connected to {_PLATFORM_NAMES[platform]}, sir."

        platform = (parameters.get("platform") or "").strip().lower()
        if platform not in _PLATFORMS:
            return (f"Sir, please specify a platform: {', '.join(_PLATFORMS)}.")
        if not _has_creds(platform):
            return (f"{_PLATFORM_NAMES[platform]} isn't connected yet, sir. "
                    f"Say 'connect {_PLATFORM_NAMES[platform]}' and give me the API token first.")

        if action == "post":
            text = (parameters.get("text") or "").strip()
            if not text:
                return "Sir, please give me the text to post."
            return _post(platform, text)

        if action == "get_feed":
            return _feed(platform)

        if action == "search":
            query = (parameters.get("query") or "").strip()
            if not query:
                return "Sir, what should I search for?"
            return _search(platform, query)

        return f"Sir, I don't recognize the action '{action}'."

    except Exception as e:
        return f"Sir, social_media failed: {e}"


# ── platform stubs (wire real APIs here once credentials exist) ─────────────

def _post(platform: str, text: str) -> str:
    # Real implementation would call each platform's API with the stored token.
    # Until then this is a safe, visible placeholder that never sends anything.
    return (
        f"I would post '{text[:60]}' to {_PLATFORM_NAMES[platform]}, sir, but "
        f"the live API call isn't wired yet. Add it in plugins/social_media.py "
        f"under _post(). Nothing was sent."
    )


def _feed(platform: str) -> str:
    return (
        f"Reading {_PLATFORM_NAMES[platform]}'s feed isn't wired yet, sir. "
        f"Implement _feed() in plugins/social_media.py."
    )


def _search(platform: str, query: str) -> str:
    return (
        f"Searching {_PLATFORM_NAMES[platform]} for '{query}' isn't wired yet, "
        f"sir. Implement _search() in plugins/social_media.py."
    )
