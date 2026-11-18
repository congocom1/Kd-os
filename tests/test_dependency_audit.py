"""Offline utility integration and its read permission boundary."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.dependency_audit import audit_manifest
from actions.dependency_audit import dependency_audit


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("KD_PROJECT_ROOTS", str(tmp_path))
    return tmp_path


def test_real_upstream_findings_offline(project):
    path = project / "requirements.txt"
    path.write_text("pathlib==1.0.1\nrequests\nurllib3==1.0\nurllib3==2.0\n")
    with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
        report = audit_manifest(str(path))
    assert report["summary"]["online"] is False
    assert report["summary"]["total"] >= 3
    assert any(f["package"] == "pathlib" for f in report["findings"])
    assert path.read_text().startswith("pathlib==1.0.1")


@pytest.mark.parametrize("name,text", [
    ("package.json", '{"dependencies":{"example":"*"}}'),
    ("pyproject.toml", '[project]\ndependencies=["requests"]'),
])
def test_other_formats(project, name, text):
    path = project / name
    path.write_text(text)
    assert audit_manifest(str(path))["summary"]["total"] > 0


def test_outside_root_denied(tmp_path, monkeypatch):
    monkeypatch.delenv("KD_PROJECT_ROOTS", raising=False)
    path = tmp_path / "requirements.txt"
    path.write_text("requests")
    with pytest.raises(PermissionError):
        audit_manifest(str(path))


def test_symlink_escape_denied(project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "requirements.txt"
    outside.write_text("requests")
    link = project / "requirements.txt"
    link.symlink_to(outside)
    with pytest.raises(PermissionError):
        audit_manifest(str(link))


def test_size_and_filename_limits(project):
    path = project / "requirements.txt"
    path.write_bytes(b"x" * 131073)
    with pytest.raises(ValueError, match="128 KiB"):
        audit_manifest(str(path))
    secret = project / "secrets.json"
    secret.write_text("{}")
    with pytest.raises(ValueError, match="Only"):
        audit_manifest(str(secret))


def test_action_rejects_network_and_malformed_inputs():
    for params in (None, {}, {"manifest": "requirements.txt", "online": True}):
        assert json.loads(dependency_audit(params))["status"] == "error"


def test_action_registry_integration():
    from core.action_loader import _validate
    from actions import dependency_audit as action
    record = _validate(action, "dependency_audit.py")
    assert record.valid
    assert record.name == "dependency_audit"