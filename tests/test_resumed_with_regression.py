"""Regression test for UnboundLocalError: _resumed_with in JarvisLive._run_sessions.

The resumption flag was assigned inside the `try` block that opens a session.
If any earlier call failed, the flag never existed and the `except` handler that
inspects it raised a second, masking error instead of reconnecting.  The flag is
now initialised before the fallible call.
"""
import re
from pathlib import Path

import main


def test_resumed_with_is_initialised_before_the_except_handler() -> None:
    source = Path(main.__file__).read_text()
    start = source.index("async def _run_sessions")
    candidates = [m.start() for m in re.finditer(r"\n    (?:async )?def ", source[start + 1:])]
    end = start + 1 + min(candidates) if candidates else len(source)
    body = source[start:end]

    try_index = body.index("except BaseException")
    init_index = body.index("_resumed_with = False")

    assert init_index < try_index, "_resumed_with must be initialised before the except handler"