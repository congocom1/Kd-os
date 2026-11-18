"""Shared pytest environment setup.

The project tests run without a desktop session. Configure Qt before test
modules import PyQt6, and isolate the incompatible optional Logfire Pydantic
plugin before Pydantic creates its first model.
"""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.qt_bootstrap import configure_qt_environment


configure_qt_environment()
