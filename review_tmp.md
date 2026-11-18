## Review Team: JARVIS Fullstack Qt Bootstrap Fix

**Mode**: single  
**Context**: Comprehensive fix for Qt platform crash, Pydantic plugin isolation, F821 undefined-name errors, and GUI test unblocking on Python 3.14/Conda Linux.

**Changed files** (16 files):
- `core/qt_bootstrap.py` — New: Qt runtime discovery, LD_LIBRARY_PATH/configuration, transparent re-exec, logfire plugin isolation, WebEngine path configuration
- `main.py` — Bootstrap import before UI; undefined `loop` fix; `reexec=__name__=="__main__"` guard
- `ui.py` — `AA_ShareOpenGLContexts` attribute; `QSpinBox` import; WebEngine offscreen guard
- `launch.sh` — PyQt6-Qt6 metadata-based plugin path discovery
- `actions/background_monitor.py` — Rewritten to use `memory.memory_manager.load_memory()/save_memory()`
- `actions/notification_service.py` — Rewritten: player passed into `_deliver_notification`; headless delivery; dead path removed
- `actions/troubleshooting.py` — Fixed `except ... as exc` in log-cleanup failure path
- `actions/browser_control.py` — Added module-level `logger`
- `actions/code_helper.py` — Added module-level `logger`
- `actions/desktop.py` — Added module-level `logger`
- `actions/dev_agent.py` — Added module-level `logger`
- `actions/file_controller.py` — Added module-level `logger`
- `actions/review_team.py` — Added module-level `logger`
- `tests/test_qt_bootstrap.py` — New: 5 regression tests for plugin discovery, platform selection, WebEngine paths, logfire isolation
- `tests/test_action_regressions.py` — New: 5 regression tests (monitor persistence, round-trip, notification→player+disk, headless, remediation logging)
- `tests/conftest.py` — Session-level Qt/env bootstrap for test suites

**Verification results**:
- `python3 main.py` starts cleanly: no Qt platform plugin error, no core dump, no Logfire/Pydantic warning
- Full pytest suite: **345 tests, 0 failures, 0 errors, 4 skipped**
- Previously blocked GUI tests: **15 passed** (test_futuristic_ui.py, test_hud_layout.py, test_native_pytorch3d.py)
- Flake8 `F821` scan: clean across all modules
- `compileall`: clean for core actions plugins providers tests main.py ui.py
- Targeted regression tests: **10 passed** (test_qt_bootstrap.py + test_action_regressions.py)

**Known remaining issues** (outside scope of this fix):
- PulseAudio sample rate mismatch causing microphone reconnect loops (device configuration)
- Gemini API quota exhaustion (runtime configuration)
- Wayland session device access limitation (session design)

---
**Reviewer prompts** — each reviewer should stay within their mandated area and return only concrete, actionable findings with file and line references. If no issues, say "No [area] issues found."