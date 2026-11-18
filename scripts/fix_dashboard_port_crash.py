#!/usr/bin/env python3
"""Apply the dashboard port-crash fix to a Mark-LVI checkout.

WHAT IT FIXES

    [Dashboard] port 8001 is already in use — another copy of JARVIS is
                probably running ...
    [Dashboard] Type by hand:  10.0.0.10:8000
    ERROR:    [Errno 98] error while attempting to bind on address
              ('0.0.0.0', 8000): [errno 98] address already in use
    SystemExit: 3                      <-- uvicorn's STARTUP_FAILURE
    asyncio.exceptions.CancelledError  <-- the Live session, killed by it

The diagnostic reads like a network fault because that is exactly what it
looked like. uvicorn answers a busy port with sys.exit(), which raises
SystemExit — a BaseException, so no `except Exception` above it ever sees it.
Left inside an asyncio task it stops the event loop, and the loop stops by
re-raising on the main thread with every other task torn down mid-flight. The
Gemini Live websocket was resolving DNS at that moment, so it surfaced as a
CancelledError and the app reconnected forever.

Nothing that is a convenience feature — a redirect to HTTPS — is allowed that
kind of reach.

THE FIX, IN TWO LAYERS
  1. probe the redirector's port before binding, so the failure is a sentence
     rather than an exception (the same pattern the secure server already uses)
  2. wrap the redirector task so that nothing at all — SystemExit included —
     can escape it, which also covers `serve()` itself

USAGE
    python3 scripts/fix_dashboard_port_crash.py [path/to/dashboard/server.py]

Safe to re-run: it detects an already-patched file and does nothing.
"""
import re
import sys
from pathlib import Path

# The tail of _serve_redirector(), as it appears in every version seen so far.
_OLD_TAIL = """cfg = uvicorn.Config(bounce, host="0.0.0.0", port=PORT,
                             log_level="warning")
        print(f"[Dashboard] Type by hand:  {self._ip}:{PORT}  "
              f"(sends you to the secure page)")
        await uvicorn.Server(cfg).serve()
"""

_NEW_TAIL = """# CAN THIS PORT ACTUALLY BE TAKEN?
        #
        # The secure server already probes its own port (see serve()); this one
        # is the easy one to forget, and forgetting it is not cosmetic.
        #
        # uvicorn answers a busy port by calling sys.exit(STARTUP_FAILURE),
        # which raises SystemExit — a BaseException, so no `except Exception`
        # anywhere above ever sees it. In an asyncio task that is fatal: the
        # loop re-raises it on the main thread and tears down every other task
        # that is mid-flight. The symptom it leaves behind is unrelated and
        # looks like a network fault — the Gemini Live websocket is cancelled
        # during DNS, so the app prints a CancelledError traceback and starts
        # reconnecting forever.
        #
        # So: ask first. A millisecond spent here turns a dead assistant into
        # one sentence about a port.
        import socket as _socket
        _probe = _socket.socket()
        try:
            _probe.bind(("0.0.0.0", PORT))
        except OSError as exc:
            _probe.close()
            self._redirector_bind_error = (
                f"port {PORT} is already in use — the type-by-hand redirect "
                f"is off, but the dashboard itself is unaffected "
                f"({exc.__class__.__name__})")
            print(f"[Dashboard] {self._redirector_bind_error}")
            return
        _probe.close()

        cfg = uvicorn.Config(bounce, host="0.0.0.0", port=PORT,
                             log_level="warning")
        print(f"[Dashboard] Type by hand:  {self._ip}:{PORT}  "
              f"(sends you to the secure page)")
        await uvicorn.Server(cfg).serve()

    async def _serve_redirector_guarded(self) -> None:
        \"\"\"Run the redirector, and let nothing at all escape.

        `except Exception` does not cover SystemExit or KeyboardInterrupt, and
        uvicorn's own bind-failure path is SystemExit. A BaseException leaving
        this task would stop the event loop, which is what a redirect-to-HTTPS
        convenience feature must never be allowed to be worth.
        \"\"\"
        try:
            await self._serve_redirector()
        except asyncio.CancelledError:
            raise                       # shutdown was asked for; let it through
        except BaseException as exc:
            print(f"[Dashboard] Redirector stopped ({exc.__class__.__name__}) — "
                  f"the dashboard itself is unaffected.")
"""

_OLD_SPAWN = "asyncio.create_task(self._serve_redirector())"
_NEW_SPAWN = "asyncio.create_task(self._serve_redirector_guarded())"

# Backstop around serve()'s own uvicorn call, for the TOCTOU window the probe
# cannot quite close.
_OLD_FINAL = '''        print(f"[Dashboard] {self.get_url()}")
        print("[Dashboard] Press 'Remote Control' in JARVIS UI to get the QR code.")
        await uvicorn.Server(cfg).serve()'''

_NEW_FINAL = '''        print(f"[Dashboard] {self.get_url()}")
        print("[Dashboard] Press 'Remote Control' in JARVIS UI to get the QR code.")

        # The probe above closes the TOCTOU window almost all the way, but
        # "almost" is where uvicorn's sys.exit(STARTUP_FAILURE) lives, and a
        # SystemExit escaping this task would stop the whole event loop —
        # taking the assistant down for what is a dashboard that could not
        # start. Keep the probe for its good message, and this as the backstop.
        try:
            await uvicorn.Server(cfg).serve()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._bind_error = (
                f"the dashboard server stopped ({exc.__class__.__name__}) — "
                f"everything else keeps running")
            print(f"[Dashboard] {self._bind_error}")'''

_OLD_INIT = "        self._bind_error: str = \"\""

_NEW_INIT = '''        self._bind_error: str = ""
        # Same idea for the type-by-hand redirector on PORT: a busy port there
        # is not a reason to stop anything, so it gets its own slot for the UI
        # to mention rather than a silent absence.
        self._redirector_bind_error: str = ""'''


def patch(target: Path) -> bool:
    src = target.read_text(encoding="utf-8")
    out = src
    done = []

    if "_serve_redirector_guarded" in out:
        print(f"{target}: already patched — nothing to do.")
        return None          # neither success nor failure; it is already done

    if _OLD_TAIL in out:
        out = out.replace(_OLD_TAIL, _NEW_TAIL, 1)
        done.append("redirector port probe + BaseException guard")
    else:
        print(f"{target}: WARNING — could not find _serve_redirector's tail.")
        print("           Apply step 1 by hand; the rest of this script still runs.")

    if _OLD_SPAWN in out:
        out = out.replace(_OLD_SPAWN, _NEW_SPAWN, 1)
        done.append("serve() now spawns the guarded redirector")

    if _OLD_FINAL in out:
        out = out.replace(_OLD_FINAL, _NEW_FINAL, 1)
        done.append("backstop around serve()'s own uvicorn call")

    if _OLD_INIT in out:
        out = out.replace(_OLD_INIT, _NEW_INIT, 1)
        done.append("_redirector_bind_error attribute initialised")

    if out == src:
        print(f"{target}: nothing matched — this file may be a different version.")
        return False

    target.write_text(out, encoding="utf-8")

    compile(out, str(target), "exec")
    for item in done:
        print(f"  + {item}")
    print(f"{target}: patched and syntax-checked OK.")
    return True


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        targets = [Path(a) for a in args]
    else:
        targets = [Path("dashboard/server.py")]
    bad = 0
    for t in targets:
        if not t.is_file():
            print(f"{t}: no such file.")
            bad += 1
            continue
        if patch(t) is False:
            bad += 1
    # None means "already patched" — that is a success, not a failure, so it
    # must not flip the exit status. Only a real failure (False) does.
    sys.exit(1 if bad else 0)