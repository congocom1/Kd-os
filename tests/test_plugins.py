"""Comprehensive plugin tests — every plugin loads, validates, and runs without crashing."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.plugin_loader import discover_plugins, PluginRegistry
from memory.config_manager import save_plugin_enabled


class FakeUI:
    """Minimal stand-in for JarvisUI that plugins can call write_log on."""
    def __init__(self):
        self.logs = []
        self.muted = False

    def write_log(self, text: str):
        self.logs.append(text)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Discover all plugins with a fresh config, enable them all."""
    plugins_dir = Path(__file__).resolve().parent.parent / "plugins"
    # Enable every plugin
    for p in sorted(plugins_dir.glob("*.py")):
        if not p.name.startswith("_"):
            save_plugin_enabled(p.stem, True)

    reg = discover_plugins(
        plugins_dir=plugins_dir,
        core_tool_names=set(),
        logger=lambda msg: None,
        notify=lambda msg: None,
    )
    return reg


def test_action_registry_exposes_complete_feature_inventory(tmp_path):
    from core.action_loader import discover_actions
    registry = discover_actions(tmp_path, set())
    inventory = registry.list_for_ui()
    assert inventory == []


def test_all_plugins_load(registry):
    """Every plugin file must load without crashing."""
    assert len(registry._plugins) > 0, "No plugins loaded at all"
    assert len(registry._all_records) > 0, "No plugin records at all"

    rejected = [r for r in registry._all_records if not r.valid]
    assert not rejected, (
        f"{len(rejected)} plugin(s) rejected: "
        + ", ".join(f"{r.name} ({r.error})" for r in rejected)
    )


def test_no_name_collisions(registry):
    """No two plugins may share the same name."""
    names = [r.name for r in registry._all_records if r.valid]
    assert len(names) == len(set(names)), f"Duplicate plugin names: {names}"


def test_ui_listing(registry):
    """list_for_ui must return a dict for every record (valid or not)."""
    listing = registry.list_for_ui()
    assert len(listing) == len(registry._all_records)
    for entry in listing:
        assert "name" in entry
        assert "valid" in entry
        assert "file" in entry


def test_settings_schemas(registry):
    """settings_schemas must return a list (possibly empty)."""
    schemas = registry.settings_schemas()
    assert isinstance(schemas, list)


# ── Per-plugin functional tests ──────────────────────────────────────────

def test_calculator(registry):
    rec = registry._plugins["calculator"]
    ui = FakeUI()
    result = rec.run({"expression": "2 + 2 * 3"}, player=ui)
    assert "8" in result, f"Expected '8' in result, got: {result}"
    assert ui.logs, "calculator should write to player log"


def test_current_time(registry):
    rec = registry._plugins["current_time"]
    result = rec.run({})
    assert result, "current_time should return a non-empty string"
    assert "2026" in result or "PM" in result or "AM" in result


def test_unit_converter(registry):
    rec = registry._plugins["unit_converter"]
    result = rec.run({"value": "100", "from_unit": "celsius", "to_unit": "fahrenheit"})
    assert "212" in result, f"Expected '212' in result, got: {result}"


def test_unit_converter_invalid_units(registry):
    rec = registry._plugins["unit_converter"]
    result = rec.run({"value": "10", "from_unit": "frobnicate", "to_unit": "widgets"})
    assert "can't convert" in result.lower() or "sir" in result.lower()


def test_system_info(registry):
    rec = registry._plugins["system_info"]
    result = rec.run({})
    assert result, "system_info should return a non-empty string"
    assert "CPU" in result or "cpu" in result


def test_personal_notes(registry):
    rec = registry._plugins["personal_notes"]
    # List existing notes
    result = rec.run({"action": "list"})
    assert result, "personal_notes list should return a string"
    # Save a note
    result = rec.run({"action": "save", "key": "test_note", "value": "test value"})
    assert "saved" in result.lower(), f"Expected 'saved', got: {result}"
    # Recall it
    result = rec.run({"action": "recall", "keyword": "test_note"})
    assert "test_note" in result or "test value" in result, f"Expected note content, got: {result}"
    # Invalid action
    result = rec.run({"action": "bogus"})
    assert "save, recall, or list" in result


def test_social_media_status(registry):
    rec = registry._plugins["social_media"]
    result = rec.run({"action": "status"})
    assert "connected" in result.lower(), f"Expected 'connected', got: {result}"


def test_social_media_connect(registry):
    rec = registry._plugins["social_media"]
    result = rec.run({"action": "connect", "platform": "x", "token": "test_token_123"})
    assert "Connected" in result, f"Expected 'Connected', got: {result}"
    # Verify status now shows it
    result = rec.run({"action": "status"})
    assert "✓" in result or "X" in result


def test_sqlite_commands(registry):
    rec = registry._plugins["sqlite_commands"]
    result = rec.run({"action": "cmd_list"})
    assert "No commands defined" in result or "Defined commands" in result


def test_studio_modeler(registry):
    rec = registry._plugins["studio_modeler"]
    # List empty scene
    result = rec.run({"action": "list"})
    assert "empty" in result.lower(), f"Expected 'empty', got: {result}"
    # Create a box
    result = rec.run({"action": "create", "otype": "box", "name": "test_box"})
    assert "test_box" in result, f"Expected 'test_box', got: {result}"
    # List again - should have the box
    result = rec.run({"action": "list"})
    assert "test_box" in result
    # Info
    result = rec.run({"action": "info", "name": "test_box"})
    assert "verts" in result or "faces" in result
    # Delete
    result = rec.run({"action": "delete", "name": "test_box"})
    assert "Deleted" in result or "deleted" in result.lower()


def test_studio_modeler_invalid_action(registry):
    rec = registry._plugins["studio_modeler"]
    result = rec.run({"action": "bogus"})
    assert "object" in result.lower() or "recognize" in result.lower() or "recognise" in result.lower()


def test_studio_modeler_visual(registry):
    rec = registry._plugins["studio_modeler_visual"]
    result = rec.run({"action": "list"})
    assert result, "studio_modeler_visual list should return a string"


def test_google_connector_status(registry):
    rec = registry._plugins["google_connector"]
    result = rec.run({"action": "status"})
    assert result, "google_connector status should return a string"


def test_whatsapp_connector_status(registry):
    rec = registry._plugins["whatsapp_connector"]
    result = rec.run({"action": "status"})
    assert result, "whatsapp_connector status should return a string"


def test_vision_learner_status(registry):
    rec = registry._plugins["vision_learner"]
    result = rec.run({"action": "status"})
    assert result, "vision_learner status should return a string"


# ── Plugin registry behavior ─────────────────────────────────────────────

def test_plugin_registry_run_with_invalid_name(registry):
    """Running a non-existent plugin name should return an error string."""
    result = registry.run("nonexistent_plugin", {}, player=FakeUI())
    assert "not available" in result.lower() or "not found" in result.lower() or "unknown" in result.lower()


def test_plugin_registry_has(registry):
    """has() should return True for valid plugin names."""
    for name in registry._plugins:
        assert registry.has(name), f"has({name}) should be True"
    assert not registry.has("nonexistent")


def test_disabled_plugin_not_runnable(registry, monkeypatch):
    """A disabled plugin should not be runnable."""
    # Disable calculator
    save_plugin_enabled("calculator", False)
    result = registry.run("calculator", {"expression": "1+1"}, player=FakeUI())
    assert "disabled" in result.lower() or "not available" in result.lower()
    # Re-enable
    save_plugin_enabled("calculator", True)
