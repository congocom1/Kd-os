"""Isolated restart, routing and approval tests; no real tools or inference."""
import asyncio
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core import confirm
from providers.llm_router import LLMRouter


def router():
    return LLMRouter({"models": [
        {"name": "small", "tier": "cheap", "cost": 1, "vision": False},
        {"name": "large", "tier": "premium", "cost": 2, "vision": True},
    ]})


def test_router_no_higher_tier():
    fleet = router()
    fleet._current = fleet.models[-1]
    assert fleet.select(escalate=True) is None


def test_router_filters_capabilities_and_failed_models():
    fleet = router()
    assert fleet.select(needs_vision=True).name == "large"
    fleet.models[1].failures = 3
    assert fleet.select(needs_vision=True) is None


async def _collect_chat(router, messages):
    """Helper to collect full response from router's async generator."""
    result = ""
    async for event in router.chat(messages):
        if "text" in event:
            result += event["text"]
    return result


def test_router_retries_once():
    fleet = router()
    
    # Create async generators that yield events
    async def first_chat(*args, **kwargs):
        raise RuntimeError("unavailable")
        yield  # make it an async generator
    
    async def second_chat(*args, **kwargs):
        yield {"text": "verified response"}
    
    fleet.models[0]._llm = SimpleNamespace(chat=first_chat)
    fleet.models[1]._llm = SimpleNamespace(chat=second_chat)
    response = asyncio.run(_collect_chat(fleet, []))
    assert response == "verified response"
    # Note: await_count doesn't work the same way with async generators
    assert fleet.current.name == "large"


@pytest.fixture
def approval(monkeypatch):
    monkeypatch.setattr(confirm, "_pending", None)
    monkeypatch.setattr(confirm, "_show_cb", lambda *args: None)
    monkeypatch.setattr(confirm, "_hide_cb", lambda: None)
    monkeypatch.setattr(confirm, "_log_cb", None)
    # Run only the test callback synchronously, making assertions deterministic.
    monkeypatch.setattr(confirm.threading, "Thread",
                        lambda target, **kwargs: SimpleNamespace(start=target))
    calls = []
    return calls, lambda: calls.append("executed")


def test_headless_confirmation_fails_closed(approval, monkeypatch):
    calls, action = approval
    monkeypatch.setattr(confirm, "_show_cb", None)
    confirm.request("test", "Test", "Details", action)
    confirm.resolve(True)
    assert calls == []


@pytest.mark.parametrize("accepted", [False, True])
def test_confirmation_cancel_or_single_execution(approval, accepted):
    calls, action = approval
    confirm.request("test", "Test", "Details", action)
    confirm.resolve(accepted)
    confirm.resolve(True)
    assert calls == (["executed"] if accepted else [])


def test_expired_confirmation_never_executes(approval, monkeypatch):
    calls, action = approval
    monkeypatch.setattr(confirm.time, "monotonic", lambda: 0)
    confirm.request("test", "Test", "Details", action)
    monkeypatch.setattr(confirm.time, "monotonic", lambda: confirm.TIMEOUT_SECONDS + 1)
    confirm.resolve(True)
    assert calls == []


def test_memory_survives_process_restart(tmp_path):
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / "memory.json"
    setup = "from pathlib import Path; from memory import memory_manager as m; import sys; m.MEMORY_PATH=Path(sys.argv[1]); "
    write = setup + "m.save_memory({'notes': {'restart': {'value': 'KD test'}}})"
    read = setup + "assert m.load_memory()['notes']['restart']['value'] == 'KD test'"
    for script in (write, read):
        subprocess.run([sys.executable, "-c", script, str(path)], cwd=root,
                       check=True, capture_output=True, timeout=10)