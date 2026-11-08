"""The reading API accepts str and path-like paths, not only pathlib.Path (issue #98)."""

from __future__ import annotations

import errno
import gzip
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import CsvQualityError, profile_file, read_table
from csv_quality_report.errors import EXIT_EMPTY, EXIT_ENCODING, EXIT_IO, FileReadError
from csv_quality_report.reader import _rereadable, open_rows

WriteCsv = Callable[..., Path]
DATA = "id;peso;fecha\n1;12,5;2026-10-01\n2;;2026-10-02\n2;;2026-10-02\n"


class PathLike(os.PathLike[str]):
    """A path-like object that is not a pathlib.Path."""

    def __init__(self, path: Path) -> None:
        self._path = str(path)

    def __fspath__(self) -> str:
        return self._path


def test_str_and_path_like_give_the_same_report(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    expected = profile_file(path, delimiter="auto", decimal_comma=True)
    assert profile_file(str(path), delimiter="auto", decimal_comma=True) == expected
    assert profile_file(PathLike(path), delimiter="auto", decimal_comma=True) == expected
    assert (expected.rows, expected.duplicate_rows) == (3, 1)


def test_read_table_and_open_rows_take_str(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    assert read_table(str(path), delimiter=";") == read_table(path, delimiter=";")
    with open_rows(str(path), delimiter=";") as stream:
        assert stream.path == path  # still a Path for the rest of the reader
        assert stream.header == ["id", "peso", "fecha"]
        assert len(list(stream)) == 3


def test_gzip_file_as_str(write_csv: WriteCsv) -> None:
    path = write_csv(gzip.compress(DATA.encode()), "data.csv.gz")
    report = profile_file(str(path), delimiter="auto", decimal_comma=True)
    assert (report.compressed, report.rows) == (True, 3)


def test_dash_as_str_reads_standard_input(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BufferedReader(io.BytesIO(DATA.encode()))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(buffer, encoding="utf-8"))
    report = profile_file("-", delimiter="auto", decimal_comma=True)
    assert report.rows == 3


def test_missing_file_as_str_is_a_read_error(tmp_path: Path) -> None:
    missing = str(tmp_path / "nope.csv")
    with pytest.raises(FileReadError) as excinfo:
        profile_file(missing)
    assert isinstance(excinfo.value, CsvQualityError)
    assert excinfo.value.exit_code == EXIT_IO
    assert f"cannot read '{missing}'" in excinfo.value.message


needs_fifo = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO support required")


def _fifo(tmp_path: Path, via_symlink: bool = False) -> tuple[Path, Path]:
    """A named pipe in ``tmp_path`` and the path to give the reader (maybe a symlink)."""
    fifo = tmp_path / "pipe.csv"
    os.mkfifo(fifo)
    if not via_symlink:
        return fifo, fifo
    link = tmp_path / "linked.csv"
    try:
        link.symlink_to(fifo)
    except (OSError, NotImplementedError) as error:  # depends on the OS
        pytest.skip(f"Symbolic links are unavailable: {error}")
    return fifo, link


def _write_when_read(fifo: Path, data: bytes, proc: subprocess.Popen[str]) -> None:
    """Write ``data`` into ``fifo`` once ``proc`` opened it for reading.

    A plain blocking open would hang the test if the reader never opens the
    pipe (it failed first), so poll with a non-blocking open, which fails
    with ENXIO while there is no reader, until the reader exits or 10 s pass.
    """
    deadline = time.monotonic() + 10
    while True:
        try:
            descriptor = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as error:
            if error.errno != errno.ENXIO or proc.poll() is not None:
                return  # the reader exited without opening the pipe
            if time.monotonic() > deadline:  # only on a hang
                return
            time.sleep(0.01)
            continue
        break
    os.set_blocking(descriptor, True)
    with os.fdopen(descriptor, "wb") as writer:
        try:
            writer.write(data)
        except BrokenPipeError:  # the reader stopped early
            pass


def _run_with_writer(
    args: list[str], fifo: Path, data: bytes, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run the CLI first and write ``data`` into ``fifo`` afterwards, as in a mkfifo pipeline.

    The reader opens the pipe before any writer exists, so the open has to
    wait for the writer (#293). The deadline turns a hang into a failure.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "csv_quality_report", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        _write_when_read(fifo, data, proc)
        stdout, stderr = proc.communicate(timeout=10)
    finally:
        proc.kill()
        proc.wait()
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


@needs_fifo
@pytest.mark.parametrize("via_symlink", [False, True])
def test_named_pipe_is_read_like_a_file(
    tmp_path: Path, cli_env: dict[str, str], via_symlink: bool
) -> None:
    # Pipes worked in every release up to 0.23.0; #292 refused them (#293).
    fifo, selected = _fifo(tmp_path, via_symlink)
    args = [str(selected), "--delimiter", "auto", "--decimal-comma", "--format", "json"]
    proc = _run_with_writer(args, fifo, DATA.encode(), cli_env)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert (report["source"], report["rows"], report["duplicate_rows"]) == (str(selected), 3, 1)


@needs_fifo
def test_gzip_through_a_named_pipe(tmp_path: Path, cli_env: dict[str, str]) -> None:
    fifo, _ = _fifo(tmp_path)
    args = [str(fifo), "--delimiter", "auto", "--decimal-comma", "--format", "json"]
    proc = _run_with_writer(args, fifo, gzip.compress(DATA.encode()), cli_env)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert (report["compressed"], report["rows"]) == (True, 3)


@needs_fifo
def test_named_pipe_through_the_python_api(tmp_path: Path) -> None:
    fifo, _ = _fifo(tmp_path)
    writer = threading.Thread(target=lambda: fifo.write_bytes(DATA.encode()), daemon=True)
    writer.start()
    try:
        report = profile_file(fifo, delimiter="auto", decimal_comma=True)
    finally:
        writer.join(timeout=10)
    assert (report.rows, report.duplicate_rows) == (3, 1)


@needs_fifo
def test_invalid_byte_in_a_named_pipe_is_not_located_by_reopening_it(
    tmp_path: Path, cli_env: dict[str, str]
) -> None:
    # Locating the byte would open the pipe a second time and wait forever
    # for a writer that already left, which 0.23.0 did.
    fifo, _ = _fifo(tmp_path)
    proc = _run_with_writer([str(fifo)], fifo, b"sku,peso\n\xf1and\xfa,2\n", cli_env)
    assert proc.returncode == EXIT_ENCODING, proc.stderr
    assert proc.stderr == (
        f"error: '{fifo}' is not valid UTF-8 (the offset of the invalid byte is not "
        "available: the input (a pipe) cannot be read again); re-save the file as "
        "UTF-8, or name its encoding with --encoding (spreadsheet exports are often "
        "cp1252)\n"
    )
    assert proc.stdout == ""


@pytest.mark.skipif(not os.path.exists("/dev/null"), reason="needs /dev/null")
def test_character_device_is_read(cli_env: dict[str, str]) -> None:
    # /dev/stdin and /dev/fd/N may be character devices: they are read, so
    # /dev/null is simply an empty input.
    proc = subprocess.run(
        [sys.executable, "-m", "csv_quality_report", "/dev/null"],
        capture_output=True,
        text=True,
        env=cli_env,
        timeout=10,
        check=False,
    )
    assert proc.returncode == EXIT_EMPTY, proc.stderr
    assert "regular file" not in proc.stderr and "not a file or a pipe" not in proc.stderr


def test_directory_is_a_controlled_read_error_not_csv_content(tmp_path: Path) -> None:
    expected = f"cannot read '{tmp_path}': it is a directory, not a file or a pipe"
    with pytest.raises(FileReadError, match="it is a directory") as excinfo:
        read_table(tmp_path)
    assert excinfo.value.message.startswith(expected)
    assert excinfo.value.exit_code == EXIT_IO
    with pytest.raises(FileReadError, match="it is a directory"):
        with open_rows(str(tmp_path)):
            pass  # the open fails


@pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(socket, "AF_UNIX"), reason="needs Unix sockets"
)
def test_socket_is_a_controlled_read_error(tmp_path: Path) -> None:
    path = tmp_path / "s.sock"
    server = socket.socket(socket.AF_UNIX)
    try:
        try:
            server.bind(str(path))
        except OSError as error:  # path too long on some systems
            pytest.skip(f"cannot bind a Unix socket here: {error}")
        with pytest.raises(FileReadError, match="it is a socket, not a file or a pipe"):
            read_table(path)
    finally:
        server.close()


def test_a_vanished_input_is_not_reread(tmp_path: Path) -> None:
    # The file may disappear between the read and the diagnostic.
    assert not _rereadable(tmp_path / "gone.csv")
    path = tmp_path / "here.csv"
    path.write_text("a\n")
    assert _rereadable(path)


def test_missing_file_still_reports_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.csv"
    with pytest.raises(FileReadError) as captured:
        read_table(missing)
    assert "cannot read" in str(captured.value)
    assert str(missing) in str(captured.value)
    assert "must be a regular file" not in str(captured.value)
