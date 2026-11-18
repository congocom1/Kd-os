"""KD offline dependency diagnostics for explicitly approved project roots."""
from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from core.paths import get_base_dir
from core.vendor.dependency_doctor import implementation as doctor

MAX_BYTES = 128 * 1024
MAX_ENTRIES = 500


def approved_roots():
    # Only local operator environment controls this list, never tool arguments.
    return [get_base_dir().resolve()] + [
        Path(p).expanduser().resolve()
        for p in os.environ.get("KD_PROJECT_ROOTS", "").split(os.pathsep) if p
    ]


def audit_manifest(manifest: str) -> dict:
    if not isinstance(manifest, str) or not manifest.strip():
        raise ValueError("Select requirements.txt, pyproject.toml, or package.json")
    path = Path(manifest).expanduser()
    if not path.is_absolute():
        path = get_base_dir() / path
    path = path.resolve(strict=True)
    if not any(path.is_relative_to(root) for root in approved_roots()):
        raise PermissionError("Manifest is outside KD_PROJECT_ROOTS")
    if path.name not in {"requirements.txt", "pyproject.toml", "package.json"}:
        raise ValueError("Only requirements.txt, pyproject.toml, and package.json are supported")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Manifest must be a regular file")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Manifest exceeds 128 KiB limit")
    text = raw.decode("utf-8")
    if max((len(line) for line in text.splitlines()), default=0) > 8192:
        raise ValueError("Manifest line exceeds 8192 characters")
    parser = {"requirements.txt": doctor.load_requirements,
              "pyproject.toml": doctor.load_pyproject,
              "package.json": doctor.load_package_json}[path.name]
    entries = parser(text)
    if len(entries) > MAX_ENTRIES:
        raise ValueError("Manifest exceeds 500 dependency entries")
    report = doctor.build_report(path, entries, use_online=False)
    report["limitations"] = "Offline manifest hygiene only; not a vulnerability scan or dependency resolver."
    report["untrusted_content"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description="KD offline dependency diagnostics")
    parser.add_argument("manifest")
    args = parser.parse_args()
    try:
        print(json.dumps(audit_manifest(args.manifest), indent=2))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(2, f"KD dependency audit failed: {exc}\n")


if __name__ == "__main__":
    main()