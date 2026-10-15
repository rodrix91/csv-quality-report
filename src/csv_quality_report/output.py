"""Write the files the CLI produces (``--json-output``) atomically.

A report is first written to a temporary file in the target's directory and
then moved onto the target with ``os.replace``, which is atomic when both
paths are on the same file system. A crash, a full disk or an interrupt can
therefore never leave a half-written report, and never destroys the report
an earlier run left there (often the next run's ``--baseline``). See ADR 0004.
"""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
import stat
from pathlib import Path

from .errors import OutputWriteError

_NAME_ATTEMPTS = 100  # random temporary names tried before giving up


def _create_temporary(directory: Path, name: str) -> tuple[Path, int]:
    """Create a new, empty temporary file next to the target; return its path and descriptor.

    ``O_EXCL`` never reuses an existing file, and mode ``0o666`` lets the
    umask decide the permissions, as for a file created by ``open()``.
    """
    for _ in range(_NAME_ATTEMPTS):
        candidate = directory / f".{name}.{secrets.token_hex(4)}.tmp"
        try:
            descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue
        return candidate, descriptor
    raise FileExistsError(errno.EEXIST, "no free name for a temporary file", str(directory))


def _replace(target: Path, text: str, mode: int | None) -> None:
    """Write ``text`` to a temporary file and move it onto ``target``; clean up on failure."""
    temporary, descriptor = _create_temporary(target.parent, target.name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as UTF-8, all or nothing; ``OutputWriteError`` on failure.

    On failure the temporary file is removed and ``path`` keeps its previous
    content, or still does not exist. An existing file keeps its permission
    bits. A symbolic link is written through: its target is replaced and the
    link keeps pointing at it. An existing path that is not a regular file
    (``/dev/stdout``, a named pipe) cannot be replaced, so it is written in
    place, as before.
    """
    try:
        target = Path(os.path.realpath(path))
        try:
            mode: int | None = os.stat(target).st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None and not stat.S_ISREG(mode):
            target.write_text(text, encoding="utf-8")
            return
        _replace(target, text, None if mode is None else stat.S_IMODE(mode))
    except OSError as exc:
        raise OutputWriteError(f"cannot write '{path}': {exc.strerror or exc}") from exc
