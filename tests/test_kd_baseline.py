"""Diagnostics use fakes; persistence tests never touch user memory."""
import io
import json
import subprocess
from types import SimpleNamespace

import pytest

from core import diagnostics
from memory import memory_manager


def test_memory_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_manager, "MEMORY_PATH", tmp_path / "memory.json")
    memory = memory_manager._empty_memory()
    memory["notes"]["test"] = {"value": "Bonjour KD"}
    memory_manager.save_memory(memory)
    assert memory_manager.load_memory() == memory
    assert not list(tmp_path.glob(".memory-*"))


def test_failed_replace_preserves_memory(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    path.write_text('{"notes": {"old": "preserved"}}')
    before = path.read_bytes()
    monkeypatch.setattr(memory_manager, "MEMORY_PATH", path)
    def fail(*args):
        raise OSError("injected failure")
    monkeypatch.setattr(memory_manager.os, "replace", fail)
    with pytest.raises(OSError):
        memory_manager.save_memory({"notes": {"new": "value"}})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".memory-*"))


@pytest.mark.parametrize("body,status", [
    (b'{"models":[{"name":"local:model"}]}', "reachable"),
    (b'{"models":null}', "error"), (b'[]', "error"),
    (b'invalid json', "unavailable"), (b'x' * 1_048_577, "error"),
])
def test_ollama_responses(monkeypatch, body, status):
    def open_local(url, timeout):
        assert url == "http://127.0.0.1:11434/api/tags"
        assert timeout == 3
        return io.BytesIO(body)
    monkeypatch.setattr(diagnostics, "build_opener", lambda *args:
                        SimpleNamespace(open=open_local))
    result = diagnostics.ollama_inventory()
    assert result["status"] == status
    if status == "reachable":
        assert result["inference"] == "not_tested"


def test_redirects_refused():
    assert diagnostics._NoRedirect().redirect_request(
        None, None, 302, "", {}, "https://example.com") is None


def test_gpu_timeout_is_reported(monkeypatch):
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/bin/nvidia-smi")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 5)
    monkeypatch.setattr(diagnostics.subprocess, "run", timeout)
    assert diagnostics.gpu_inventory()["status"] == "unavailable"


def test_gpu_detection_is_not_inference_verification(monkeypatch):
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/bin/nvidia-smi")
    monkeypatch.setattr(diagnostics.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout="RTX, 8151, 595.99\n"))
    result = diagnostics.gpu_inventory()
    assert result["devices"][0]["memory_mib"] == 8151
    assert result["inference"] == "not_tested"