"""Regression tests for Linux Qt runtime bootstrapping."""

from pathlib import Path

from core import qt_bootstrap


def test_qt_plugin_discovery_includes_installed_runtime(monkeypatch, tmp_path):
    """The runtime distribution, not only the bindings, owns plugin files."""
    runtime = tmp_path / "site-packages" / "PyQt6" / "Qt6"
    plugins = runtime / "plugins" / "platforms"
    plugins.mkdir(parents=True)
    (plugins / "libqxcb.so").touch()

    class FakeDistribution:
        files = (
            Path("PyQt6/Qt6/plugins/platforms/libqxcb.so"),
            Path("PyQt6/Qt6/lib/libQt6Core.so.6"),
        )

        @staticmethod
        def locate_file(path):
            return tmp_path / "site-packages" / path

    monkeypatch.setattr(
        qt_bootstrap.importlib.metadata,
        "distribution",
        lambda name: FakeDistribution(),
    )
    monkeypatch.setitem(__import__("sys").modules, "PyQt6", None)

    directories = qt_bootstrap._qt_plugin_directories()

    assert runtime / "plugins" in directories


def test_platform_selection_prefers_x11_when_display_exists(monkeypatch):
    """An X display must use xcb even in a Wayland desktop session."""
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    qt_bootstrap._select_platform()

    assert qt_bootstrap.os.environ["QT_QPA_PLATFORM"] == "xcb"


def test_webengine_paths_are_discovered_from_runtime(monkeypatch, tmp_path):
    """The WebEngine helper and resources must not rely on hard-coded paths."""
    prefix = tmp_path / "conda"
    process = prefix / "lib" / "qt6" / "QtWebEngineProcess"
    resources = prefix / "share" / "qt6" / "resources"
    locales = prefix / "share" / "qt6" / "translations" / "qtwebengine_locales"
    process.parent.mkdir(parents=True)
    resources.mkdir(parents=True)
    locales.mkdir(parents=True)
    process.touch()

    for name in (
        "QTWEBENGINEPROCESS_PATH",
        "QTWEBENGINE_RESOURCES_PATH",
        "QTWEBENGINE_LOCALES_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CONDA_PREFIX", str(prefix))
    monkeypatch.setattr(qt_bootstrap.sys, "prefix", str(prefix))
    monkeypatch.setattr(qt_bootstrap.sys, "base_prefix", str(prefix))

    qt_bootstrap._configure_webengine_paths()

    assert qt_bootstrap.os.environ["QTWEBENGINEPROCESS_PATH"] == str(process)
    assert qt_bootstrap.os.environ["QTWEBENGINE_RESOURCES_PATH"] == str(resources)
    assert qt_bootstrap.os.environ["QTWEBENGINE_LOCALES_PATH"] == str(locales)


def test_logfire_plugin_is_disabled_independently(monkeypatch):
    """The incompatible third-party plugin must not break Pydantic imports."""
    monkeypatch.delenv("PYDANTIC_DISABLE_PLUGINS", raising=False)

    class EntryPoint:
        name = "logfire-plugin"

    monkeypatch.setattr(
        qt_bootstrap.importlib.metadata,
        "entry_points",
        lambda **kwargs: (EntryPoint(),),
    )

    qt_bootstrap._disable_incompatible_logfire_plugin()

    assert qt_bootstrap.os.environ["PYDANTIC_DISABLE_PLUGINS"] == "logfire-plugin"


def test_existing_pydantic_plugin_selection_is_preserved(monkeypatch):
    """An explicit user/plugin selection must not be overwritten."""
    monkeypatch.setenv("PYDANTIC_DISABLE_PLUGINS", "another-plugin")

    qt_bootstrap._disable_incompatible_logfire_plugin()

    assert qt_bootstrap.os.environ["PYDANTIC_DISABLE_PLUGINS"] == "another-plugin"
