"""Telemetry must distinguish missing readings from genuine zero values."""
from types import SimpleNamespace

from core import telemetry


def test_gpu_memory_is_already_mib(monkeypatch):
    monkeypatch.setattr(telemetry.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout="42, 2048, 8192, 65\n"))
    result = telemetry._probeGpu()
    assert result["memory_used_mb"] == 2048
    assert result["memory_total_mb"] == 8192


def test_gpu_failure_does_not_fabricate_zero_or_leak_stderr(monkeypatch):
    monkeypatch.setattr(telemetry.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stderr="secret"))
    result = telemetry._probeGpu()
    assert result["status"] == "nvidia_smi_failed"
    assert result["memory_used_mb"] is None
    assert "secret" not in str(result)


def test_temperature_api_optional(monkeypatch):
    monkeypatch.delattr(telemetry.psutil, "sensors_temperatures", raising=False)
    assert telemetry._probeDiskTemp() == []


def test_artifact_redaction():
    from scripts.make_process_telemetry import _sanitise
    assert _sanitise({"nested": [{"api_key": "secret", "cpu": 1}]}) == {
        "nested": [{"api_key": None, "cpu": 1}]}