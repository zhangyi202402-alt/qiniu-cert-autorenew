"""文件锁（fcntl）。"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path


class LockBusy(Exception):
    """锁已被占用。"""


@contextmanager
def file_lock(path: Path, *, blocking: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    try:
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fh.fileno(), flags)
        except BlockingIOError as exc:
            raise LockBusy(str(path)) from exc
        yield fh
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()
