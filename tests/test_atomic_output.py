"""``--json-output`` is written atomically: all or nothing (issue #107)."""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import pytest

from csv_quality_report.cli import main
from csv_quality_report.errors import EXIT_WRITE, OutputWriteError
from csv_quality_report.output import write_atomic

WriteCsv = Callable[..., Path]
Symlink = Callable[[Path, Path], None]
# Windows has no POSIX permission bits: chmod only toggles the read-only flag
# and the umask does not apply, so these modes cannot be observed there (#116).
posix_modes = pytest.mark.skipif(os.name == "nt", reason="no POSIX permission bits on Windows")
DATA = "a,b\n1,x\n,y\n1,x\n"
OLD = '{"previous": "report"}\n'


def leftovers(directory: Path) -> list[str]:
    """Temporary files left in ``directory`` (none should ever be)."""
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def fail(*args: Any, **kwargs: Any) -> NoReturn:
    raise OSError(28, "No space left on device")


def test_writes_new_file_without_leftovers(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    write_atomic(target, "{}\n")
    assert target.read_text(encoding="utf-8") == "{}\n"
    assert leftovers(tmp_path) == []


@posix_modes
def test_new_file_gets_the_umask_permissions(tmp_path: Path) -> None:
    umask = os.umask(0o027)
    try:
        write_atomic(tmp_path / "report.json", "{}")
    finally:
        os.umask(umask)
    assert stat.S_IMODE((tmp_path / "report.json").stat().st_mode) == 0o640


@posix_modes
def test_replaces_existing_file_and_keeps_its_mode(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text(OLD * 500, encoding="utf-8")
    target.chmod(0o604)
    write_atomic(target, "{}\n")
    assert target.read_text(encoding="utf-8") == "{}\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o604
    assert leftovers(tmp_path) == []


def test_symlink_is_written_through(tmp_path: Path, symlink: Symlink) -> None:
    real = tmp_path / "reports" / "latest.json"
    real.parent.mkdir()
    real.write_text(OLD, encoding="utf-8")
    link = tmp_path / "link.json"
    symlink(link, real)
    write_atomic(link, "{}\n")
    assert link.is_symlink() and link.resolve() == real.resolve()
    assert real.read_text(encoding="utf-8") == "{}\n"
    assert leftovers(tmp_path) == [] and leftovers(real.parent) == []


def test_dangling_symlink_creates_its_target(tmp_path: Path, symlink: Symlink) -> None:
    link, real = tmp_path / "link.json", tmp_path / "real.json"
    symlink(link, real)
    write_atomic(link, "{}")
    assert link.is_symlink() and real.read_text(encoding="utf-8") == "{}"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes (os.mkfifo) on Windows")
def test_non_regular_file_is_written_in_place(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        write_atomic(fifo, "{}\n")
        assert os.read(reader, 100) == b"{}\n"
    finally:
        os.close(reader)
    assert stat.S_ISFIFO(fifo.stat().st_mode)  # not replaced by a regular file
    assert leftovers(tmp_path) == []


def test_dev_null_is_not_replaced() -> None:
    write_atomic(Path(os.devnull), "{}")
    assert stat.S_ISCHR(os.stat(os.devnull).st_mode)


def test_directory_target_fails(tmp_path: Path) -> None:
    with pytest.raises(OutputWriteError, match="cannot write"):
        write_atomic(tmp_path, "{}")


@pytest.mark.parametrize("step", ["fsync", "replace", "chmod"])
def test_failure_keeps_previous_report_and_removes_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    target = tmp_path / "report.json"
    target.write_text(OLD, encoding="utf-8")
    monkeypatch.setattr(os, step, fail)
    with pytest.raises(OutputWriteError) as info:
        write_atomic(target, "{}\n")
    assert info.value.message == f"cannot write '{target}': No space left on device"
    assert target.read_text(encoding="utf-8") == OLD
    assert leftovers(tmp_path) == []


def test_failure_halfway_through_write_leaves_no_partial_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.json"
    target.write_text(OLD, encoding="utf-8")
    real_fdopen = os.fdopen

    class HalfWriter:
        """A file that writes the first half of the text, then hits a full disk."""

        def __init__(self, descriptor: int, *args: Any, **kwargs: Any) -> None:
            self.handle = real_fdopen(descriptor, *args, **kwargs)

        def __enter__(self) -> HalfWriter:
            return self

        def __exit__(self, *exc: object) -> None:
            self.handle.close()

        def write(self, text: str) -> None:
            self.handle.write(text[: len(text) // 2])
            self.handle.flush()
            fail()

    monkeypatch.setattr(os, "fdopen", HalfWriter)
    with pytest.raises(OutputWriteError):
        write_atomic(target, '{"new": "report"}\n')
    assert target.read_text(encoding="utf-8") == OLD
    assert leftovers(tmp_path) == []


def test_new_target_is_not_created_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OutputWriteError):
        write_atomic(tmp_path / "report.json", "{}")
    assert list(tmp_path.iterdir()) == []


def test_interrupt_removes_temporary_and_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.json"
    target.write_text(OLD, encoding="utf-8")

    def interrupt(*args: Any) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "fsync", interrupt)
    with pytest.raises(KeyboardInterrupt):
        write_atomic(target, "{}")
    assert target.read_text(encoding="utf-8") == OLD
    assert leftovers(tmp_path) == []


def test_cleanup_error_does_not_hide_the_write_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "replace", fail)
    monkeypatch.setattr(os, "unlink", fail)
    with pytest.raises(OutputWriteError, match="No space left on device"):
        write_atomic(tmp_path / "report.json", "{}")


def test_taken_temporary_name_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    names = iter(["taken", "free"])
    monkeypatch.setattr(secrets, "token_hex", lambda nbytes: next(names))
    taken = tmp_path / ".report.json.taken.tmp"
    taken.write_text("someone else's file", encoding="utf-8")
    write_atomic(tmp_path / "report.json", "{}")
    assert taken.read_text(encoding="utf-8") == "someone else's file"
    assert (tmp_path / "report.json").read_text(encoding="utf-8") == "{}"
    assert leftovers(tmp_path) == [taken.name]


def test_no_free_temporary_name_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets, "token_hex", lambda nbytes: "taken")
    (tmp_path / ".report.json.taken.tmp").write_text("", encoding="utf-8")
    with pytest.raises(OutputWriteError, match="no free name for a temporary file"):
        write_atomic(tmp_path / "report.json", "{}")
    assert not (tmp_path / "report.json").exists()


def test_cli_failure_keeps_previous_report(
    write_csv: WriteCsv,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "report.json"
    target.write_text(OLD, encoding="utf-8")
    monkeypatch.setattr(os, "replace", fail)
    assert main([str(write_csv(DATA)), "--json-output", str(target)]) == EXIT_WRITE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"error: cannot write '{target}': No space left on device\n"
    assert target.read_text(encoding="utf-8") == OLD
    assert leftovers(tmp_path) == []


def test_cli_replaces_previous_report(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "report.json"
    target.write_text(OLD, encoding="utf-8")
    assert main([str(write_csv(DATA)), "--json-output", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["rows"] == 3
    assert leftovers(tmp_path) == []
