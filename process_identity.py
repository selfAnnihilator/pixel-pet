"""Linux process identity used by process managers and pkill."""

from __future__ import annotations

import ctypes
import os
import sys


PR_SET_NAME = 15
LINUX_NAME_LIMIT = 15


def set_process_name(name: str) -> None:
    """Set Linux ``comm`` so tools such as ``pkill -x`` can target the app."""
    if not sys.platform.startswith("linux"):
        return
    encoded = name.encode("utf-8")[:LINUX_NAME_LIMIT]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_NAME, ctypes.c_char_p(encoded), 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
