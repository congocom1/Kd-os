"""A dashboard that cannot bind a port must never be able to end the process.

Regression test for the failure mode reported from a real run:

    [Dashboard] port 8001 is already in use — another copy of JARVIS is
                probably running ...
    [Dashboard] Type by hand:  10.0.0.10:8000
    ERROR:    [Errno 98] error while attempting to bind on address
              ('0.0.0.0', 8000): [errno 98] address already in use
    ...
    SystemExit: 3                      <-- uvicorn's STARTUP_FAILURE
    ...
    asyncio.exceptions.CancelledError  <-- the Live session, cancelled by it

The diagnostic reads like a network fault because that is exactly what it
looked like. uvicorn answers a busy port with sys.exit(), which raises
SystemExit — a BaseException, so no `except Exception` above it ever sees it.
Left inside an asyncio task, it stops the event loop, and the loop stops by
re-raising on the main thread with every other task torn down mid-flight. The
Gemini Live websocket was in the middle of resolving DNS when that happened,
so it surfaced as a CancelledError and the app reconnected forever.

Nothing that is a convenience feature — a redirect to HTTPS — is allowed that
kind of reach. These tests pin the two things that give it none: the probe
that stops the bind being attempted, and the BaseException guard that stops
anything unforeseen from escaping anyway.

Async tests call asyncio.run() directly, which is the convention this repo
already uses (see tests/test_kd_stabilization.py) — there is no asyncio plugin
installed.
"""
import asyncio
import socket

import pytest

from dashboard import server as dashboard_module
from dashboard.server import DashboardServer


@pytest.fixture
def busy_port():
    """A port held by a real socket that refuses to be shared."""
    s = socket.socket()
    # No SO_REUSEADDR, deliberately: that option is what would let a second
    # socket bind a port the first already holds — the exact condition under
    # test. The probe must be able to see it.
    s.bind(("0.0.0.0", 0))
    s.listen(1)
    port = s.getsockname()[1]
    yield port
    s.close()


# ── 1. the redirector refuses to start, and says so ─────────────────────────

def test_redirector_bind_is_probed(busy_port, monkeypatch, capsys):
    server = DashboardServer()
    monkeypatch.setattr(dashboard_module, "PORT", busy_port)

    asyncio.run(server._serve_redirector())

    out = capsys.readouterr().out
    assert "already in use" in out
    assert "Type by hand" not in out, "it printed an address it never bound"
    assert server._redirector_bind_error.startswith(
        f"port {busy_port} is already in use")


def test_redirector_starts_when_port_is_free(monkeypatch, capsys):
    """The guard must not be so keen that it blocks the normal case."""
    server = DashboardServer()
    monkeypatch.setattr(dashboard_module, "PORT", 0)   # kernel picks a free port

    started = []

    class _FakeServer:
        def __init__(self, cfg):
            started.append(cfg.port)

        async def serve(self):
            started.append("served")

    monkeypatch.setattr(dashboard_module.uvicorn, "Server", _FakeServer)

    asyncio.run(server._serve_redirector())

    assert started and started[-1] == "served"
    assert "Type by hand" in capsys.readouterr().out


# ── 2. nothing escapes the redirector, SystemExit included ──────────────────

def _run_guarded_with(raisewhat):
    """Run the guard against a redirector that raises `raisewhat`."""
    server = DashboardServer()

    async def _boom():
        raise raisewhat

    server._serve_redirector = _boom
    asyncio.run(server._serve_redirector_guarded())
    return server


def test_redirector_guard_swallows_system_exit(capsys):
    _run_guarded_with(SystemExit(3))      # exactly what uvicorn raises here
    assert "Redirector stopped (SystemExit)" in capsys.readouterr().out


def test_redirector_guard_swallows_os_error(capsys):
    _run_guarded_with(OSError(98, "address already in use"))
    assert "Redirector stopped (OSError)" in capsys.readouterr().out


def test_redirector_guard_swallows_runtime_error(capsys):
    _run_guarded_with(RuntimeError("uvicorn config exploded"))
    assert "Redirector stopped (RuntimeError)" in capsys.readouterr().out


def test_redirector_guard_lets_cancellation_through():
    """Shutdown is the one thing that must still be able to end the task."""
    server = DashboardServer()

    async def _cancelled():
        raise asyncio.CancelledError()

    server._serve_redirector = _cancelled

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(server._serve_redirector_guarded())


# ── 3. the bind error slots always exist, so the UI never sees an AttributeError

def test_bind_error_slots_initialised():
    server = DashboardServer()
    assert server._bind_error == ""
    assert server._redirector_bind_error == ""


# ── 4. the mechanism, in isolation ──────────────────────────────────────────
#
# This is the part that made the real crash look like something else: not the
# OSError, but what an OSError becomes once uvicorn has translated it into
# sys.exit(). Worth proving on its own so the guard above reads as
# load-bearing rather than defensive noise.

def test_system_exit_in_a_task_cancels_its_siblings():
    """An unhandled SystemExit tears down every other task in flight.

    If the guard over the redirector is ever removed, this is what comes back:
    the Live websocket — cancelled mid-lookup, reported as a CancelledError
    traceback that names no port and no dashboard.
    """
    reached = []

    async def _victim():
        """Stands in for the Gemini Live session, mid-connect."""
        await asyncio.sleep(5)
        reached.append("victim")

    async def _killer():
        await asyncio.sleep(0)
        raise SystemExit(3)

    async def _scenario():
        victim = asyncio.create_task(_victim())
        killer = asyncio.create_task(_killer())
        await asyncio.gather(victim, killer)

    # pytest.raises() cannot see this one — SystemExit surfaces during the
    # event loop's own teardown, not from the awaited frame, so it is caught
    # by hand here instead.
    escaped = None
    try:
        asyncio.run(_scenario())
    except SystemExit as exc:
        escaped = exc

    assert escaped is not None, "SystemExit should have escaped asyncio.run()"
    assert escaped.code == 3
    assert "victim" not in reached, "the sibling task should have been cancelled"
    # There is no longer a loop to ask about — asyncio.all_tasks() itself now
    # raises "no running event loop". That is the point: the loop is gone too.


def test_guard_contains_the_failure_instead():
    """The guarded version of the same scenario leaves the loop alive."""
    alive = []

    async def _victim():
        await asyncio.sleep(0.05)
        alive.append("victim")

    async def _guarded_killer():
        try:
            raise SystemExit(3)
        except asyncio.CancelledError:
            raise
        except BaseException:
            return

    async def _scenario():
        victim = asyncio.create_task(_victim())
        killer = asyncio.create_task(_guarded_killer())
        await asyncio.gather(victim, killer)

    asyncio.run(_scenario())          # no SystemExit escapes

    assert alive == ["victim"], "the sibling task must survive"