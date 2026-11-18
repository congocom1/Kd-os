# JARVIS Development Guide

## Project Structure

```
mark-lvi/
├── actions/           # Auto-discovered actions (TOOL dict pattern)
├── plugins/           # Auto-discovered plugins (PLUGIN dict pattern)
├── providers/         # LLM, TTS, STT providers
├── core/              # Core framework modules
├── skills/            # SKILL.md skill definitions
├── memory/            # Long-term memory management
├── dashboard/         # Web dashboard frontend
├── docs/              # Documentation
├── tests/             # Test suite
├── core/
│   ├── studio_engine.py    # Self-contained 3D dev engine
│   ├── tiny_ml.py        # Pure numpy neural network
│   ├── code_evolution.py # Safe code modification pipeline
│   ├── unified_agent.py  # Unified agent interface
│   ├── skills_loader.py  # SKILL.md loader
│   ├── wake_word.py      # Local wake word detection
│   └── ...
├── main.py               # Entry point
├── ui.py                 # PyQt6 HUD
├── Dockerfile            # Container build
├── docker-compose.yml    # Docker deployment
├── requirements.txt      # Python dependencies
├── pyproject.toml        # Package configuration
├── README.md             # This file
└── .gitignore            # Git ignore rules
```

## Adding a New Action

1. Create a file in `actions/` with a `TOOL` dict and `run()` function:
```python
from core import outcome

TOOL = {
    "name": "my_action",
    "description": "What this action does",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "The action to perform",
            },
        },
        "required": ["action"],
    },
    "handler": run,
}

def run(parameters: dict, player=None, session_memory=None) -> str:
    action = parameters.get("action", "")
    if action == "do_something":
        return "Done!"
    return f"Unknown action: {action}"
```

2. The action is auto-discovered on startup — no registration needed.

## Adding a New Plugin

1. Create a file in `plugins/` with a `PLUGIN` dict and `run()` function:
```python
PLUGIN = {
    "name": "my_plugin",
    "description": "What this plugin does",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "What to do",
            },
        },
        "required": ["action"],
    },
}

def run(parameters: dict, player=None, session_memory=None) -> str:
    action = parameters.get("action", "")
    if action == "do_something":
        return "Done!"
    return f"Unknown action: {action}"
```

## Running Tests

```bash
pytest tests/
```

## Linting

```bash
flake8 .
```

## Formatting

```bash
black .
```
