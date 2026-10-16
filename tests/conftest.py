from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def write_csv(tmp_path: Path) -> Callable[..., Path]:
    """Write bytes or text to a temp CSV file and return its path."""

    def _write(content: str | bytes, name: str = "data.csv") -> Path:
        path = tmp_path / name
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8", newline="")
        else:
            path.write_bytes(content)
        return path

    return _write


@pytest.fixture
def symlink() -> Callable[[Path, Path], None]:
    """Create a symbolic link ``link`` -> ``target``, or skip where the OS forbids it.

    Windows only lets administrators, or accounts in Developer Mode, create
    symbolic links; elsewhere a failure is a real error and is raised (#116).
    """

    def _symlink(link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except OSError as exc:
            if os.name != "nt":
                raise
            pytest.skip(f"cannot create symbolic links here: {exc}")

    return _symlink


@pytest.fixture
def cli_env() -> dict[str, str]:
    """Environment for ``python -m csv_quality_report`` subprocesses.

    Puts ``src/`` on PYTHONPATH so the tests pass without ``pip install -e .``.
    """
    src = str(Path(__file__).resolve().parent.parent / "src")
    existing = os.environ.get("PYTHONPATH")
    return {**os.environ, "PYTHONPATH": src + (os.pathsep + existing if existing else "")}
