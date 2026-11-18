"""
Current Time skill — reports the current date and time.

Auto-discovered by core/plugin_loader at startup.
"""

from datetime import datetime

PLUGIN = {
    "name": "current_time",
    "description": (
        "Tells the user the current date and time, optionally in a specific "
        "timezone (IANA name, e.g. 'Europe/London', 'America/New_York', 'UTC'). "
        "Use when the user asks what time it is or what the date is."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "timezone": {
                "type": "STRING",
                "description": "Optional IANA timezone name, e.g. 'UTC', 'Europe/London', 'America/New_York'",
            },
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    tz_name = (parameters.get("timezone") or "").strip()
    try:
        if tz_name:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_name)
            now = datetime.now(tz)
        else:
            now = datetime.now()
    except Exception:
        return f"Sir, I don't recognise the timezone '{tz_name}'."

    answer = now.strftime("It is %I:%M %p on %A, %B %d, %Y.")
    if tz_name:
        answer = f"In {tz_name}, " + answer
    else:
        answer = "Locally, " + answer
    if player:
        try:
            player.write_log(f"JARVIS: {answer}")
        except Exception:
            pass
    return answer
