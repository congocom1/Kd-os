"""KD process-local camera leases. Frames are never persisted or transmitted.

Consumers share one native capture per index. Reads are serialized; closing a
preview cannot close a device still leased by gesture tracking. Native driver
calls may block: this is not a hard-timeout or cross-process camera broker.
"""
from __future__ import annotations

import threading

_lock = threading.RLock()
_devices = {}


class CameraLease:
    def __init__(self, index, entry):
        self._index = index
        self._entry = entry
        self._closed = False

    def isOpened(self):
        with _lock:
            return not self._closed and self._entry[0].isOpened()

    def read(self):
        with _lock:
            if self._closed:
                return False, None
            return self._entry[0].read()

    def release(self):
        with _lock:
            if self._closed:
                return
            self._closed = True
            self._entry[1] -= 1
            if self._entry[1] == 0:
                _devices.pop(self._index, None)
                self._entry[0].release()


def open_camera(index=0, backend=None):
    """Acquire a camera lease, or fail without retaining a native handle."""
    import cv2

    index = int(index)
    if index < 0:
        raise ValueError("KD camera index must be nonnegative")
    with _lock:
        entry = _devices.get(index)
        if entry is None:
            cap = cv2.VideoCapture(index, cv2.CAP_ANY if backend is None else backend)
            if not cap.isOpened():
                cap.release()
                raise RuntimeError(
                    f"Cannot open camera {index}. Check device permissions and "
                    "close camera users in other processes."
                )
            entry = [cap, 0]
            _devices[index] = entry
        entry[1] += 1
        return CameraLease(index, entry)