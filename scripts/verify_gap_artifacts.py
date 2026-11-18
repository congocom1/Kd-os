"""Reject duplicate JSON keys and incomplete release evidence; no live actions."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITS = (
    "voice_pipeline", "action_scheduler", "frontend_command_center",
    "ops_release", "security",
)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def main():
    for name in AUDITS:
        path = ROOT / "artifacts" / f"{name}_audit.json"
        data = json.loads(path.read_text(), object_pairs_hook=unique_object)
        if data.get("production_ready") is not False:
            raise ValueError(f"{name}: release readiness not established")
        if not data.get("limitations"):
            raise ValueError(f"{name}: unresolved limitations must be recorded")
    print(f"Validated {len(AUDITS)} provisional audits; production readiness NOT established.")


if __name__ == "__main__":
    main()