"""Configure the Qt runtime before PyQt creates a QApplication.

Some shared Conda environments contain the PyQt6 bindings and the PyQt6-Qt6
runtime in different site-packages directories.  In that layout Qt looks for
platform plugins next to the bindings and cannot find xcb or wayland even
though the runtime is installed.  This module locates the actual runtime and
preloads the native libraries needed by the xcb plugin.

It also disables Logfire's Pydantic entry point when it is known to be
incompatible with the environment's OpenTelemetry version.  JARVIS does not
use that plugin; leaving it enabled only produces an import warning before the
application starts.
"""

from __future__ import annotations

import ctypes
import importlib.metadata
import os
import sys
from pathlib import Path


_LOGFIRE_PLUGIN = "logfire-plugin"
_REEXEC_GUARD = "JARVIS_QT_BOOTSTRAP_COMPLETE"
_XCB_LIBRARIES = (
    "libxcb-util.so.1",
    "libxcb-image.so.0",
    "libxcb-keysyms.so.1",
    "libxcb-render-util.so.0",
    "libxcb-shape.so.0",
    "libxcb-icccm.so.4",
    "libxcb-cursor.so.0",
)


def _disable_incompatible_logfire_plugin() -> None:
    """Prevent Logfire from breaking Pydantic model creation on import."""
    if os.environ.get("PYDANTIC_DISABLE_PLUGINS"):
        return

    try:
        entry_points = importlib.metadata.entry_points(group="pydantic")
    except Exception:
        return

    if any(entry_point.name == _LOGFIRE_PLUGIN for entry_point in entry_points):
        os.environ["PYDANTIC_DISABLE_PLUGINS"] = _LOGFIRE_PLUGIN


def _qt_plugin_directories() -> list[Path]:
    """Return directories that contain Qt platform plugins."""
    candidates: list[Path] = []

    # Prefer a Conda Qt runtime that matches the installed PyQt bindings. A
    # user-site PyQt6-Qt6 runtime can otherwise be a different patch release,
    # which mixes incompatible Qt ABIs in the same process.
    for prefix in (os.environ.get("CONDA_PREFIX"), sys.prefix, sys.base_prefix):
        if not prefix:
            continue
        candidate = Path(prefix) / "lib" / "qt6" / "plugins"
        if candidate.is_dir() and candidate not in candidates:
            candidates.append(candidate)

    try:
        distribution = importlib.metadata.distribution("PyQt6-Qt6")
    except importlib.metadata.PackageNotFoundError:
        distribution = None

    if distribution is not None:
        for entry in distribution.files or ():
            path = Path(str(entry))
            parts = path.parts
            if "plugins" not in parts:
                continue
            plugin_index = len(parts) - 1 - parts[::-1].index("plugins")
            root = (
                Path(distribution.locate_file(path.parents[plugin_index]))
                / "plugins"
            )
            if root not in candidates:
                candidates.append(root)

    # Also handle a normal, unsplit PyQt6 installation.
    try:
        import PyQt6

        root = Path(PyQt6.__file__).resolve().parent / "Qt6" / "plugins"
        if root not in candidates:
            candidates.append(root)
    except Exception:
        pass

    return candidates


def _configure_plugin_path() -> None:
    """Point Qt at every installed platform-plugin directory."""
    directories = [path for path in _qt_plugin_directories() if path.is_dir()]
    if not directories:
        return

    current = os.environ.get("QT_PLUGIN_PATH", "")
    current_parts = [part for part in current.split(os.pathsep) if part]
    for directory in reversed(directories):
        value = str(directory)
        if value not in current_parts:
            current_parts.insert(0, value)
    os.environ["QT_PLUGIN_PATH"] = os.pathsep.join(current_parts)


def _native_library_directories() -> list[Path]:
    """Return native-library directories belonging to this Python runtime."""
    directories = []
    for prefix in (os.environ.get("CONDA_PREFIX"), sys.prefix, sys.base_prefix):
        if not prefix:
            continue
        path = Path(prefix) / "lib"
        if path.is_dir() and path not in directories:
            directories.append(path)
    return directories


def _preload_xcb_libraries() -> None:
    """Make Conda-provided XCB libraries visible to Qt's plugin loader."""
    if sys.platform != "linux":
        return

    for directory in _native_library_directories():
        for library in _XCB_LIBRARIES:
            path = directory / library
            if not path.exists():
                continue
            try:
                ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                # Qt will provide the final diagnostic if this library is broken.
                continue


def _select_platform() -> None:
    """Choose a Qt backend that matches the available desktop session."""
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    elif os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "wayland"
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _configure_webengine_paths() -> None:
    """Locate Qt WebEngine's helper process and runtime resources."""
    prefixes = {
        prefix
        for prefix in (os.environ.get("CONDA_PREFIX"), sys.prefix, sys.base_prefix)
        if prefix
    }

    process_candidates = []
    resource_candidates = []
    locale_candidates = []
    for prefix in prefixes:
        root = Path(prefix)
        process_candidates.extend(
            (
                root / "lib" / "qt6" / "QtWebEngineProcess",
                root / "libexec" / "QtWebEngineProcess",
            )
        )
        resource_candidates.extend(
            (
                root / "share" / "qt6" / "resources",
                root / "resources",
            )
        )
        locale_candidates.extend(
            (
                root / "share" / "qt6" / "translations" / "qtwebengine_locales",
                root / "translations" / "qtwebengine_locales",
            )
        )

    if not os.environ.get("QTWEBENGINEPROCESS_PATH"):
        for candidate in process_candidates:
            if candidate.is_file():
                os.environ["QTWEBENGINEPROCESS_PATH"] = str(candidate)
                break
    if not os.environ.get("QTWEBENGINE_RESOURCES_PATH"):
        for candidate in resource_candidates:
            if candidate.is_dir():
                os.environ["QTWEBENGINE_RESOURCES_PATH"] = str(candidate)
                break
    if not os.environ.get("QTWEBENGINE_LOCALES_PATH"):
        for candidate in locale_candidates:
            if candidate.is_dir():
                os.environ["QTWEBENGINE_LOCALES_PATH"] = str(candidate)
                break


def _reexec_with_qt_environment() -> bool:
    """Re-exec once so the loader sees the corrected native-library path."""
    if os.environ.get(_REEXEC_GUARD):
        return False

    directories = _native_library_directories()
    plugin_directories = [
        path for path in _qt_plugin_directories() if path.is_dir()
    ]
    if not directories or not plugin_directories:
        return False

    environment = os.environ.copy()
    environment[_REEXEC_GUARD] = "1"

    current_library_path = environment.get("LD_LIBRARY_PATH", "")
    library_parts = [part for part in current_library_path.split(os.pathsep) if part]
    for directory in reversed(directories):
        value = str(directory)
        if value not in library_parts:
            library_parts.insert(0, value)
    environment["LD_LIBRARY_PATH"] = os.pathsep.join(library_parts)

    os.execve(sys.executable, [sys.executable, *sys.argv], environment)
    return True  # pragma: no cover - execve either replaces or raises


def configure_qt_environment(*, reexec: bool = False) -> None:
    """Configure Qt and Pydantic before importing their runtime modules.

    ``reexec`` is enabled by the application entry point. Tests and library
    consumers can load this module without replacing their process.
    """
    _disable_incompatible_logfire_plugin()
    if sys.platform != "linux":
        return
    _configure_plugin_path()
    _preload_xcb_libraries()
    _select_platform()
    _configure_webengine_paths()
    if reexec:
        _reexec_with_qt_environment()
