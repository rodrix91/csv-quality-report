from __future__ import annotations

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
