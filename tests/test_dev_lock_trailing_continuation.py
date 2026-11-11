"""Regression tests for fully terminated hashes in a development lock."""

from pathlib import Path

import pytest

from scripts.check_dev_lock import read_hashed_versions


@pytest.mark.parametrize("trailing", ["", "\n", "    # uv metadata\n"])
def test_truncated_hashed_lock_is_rejected(
    tmp_path: Path, trailing: str
) -> None:
    path = tmp_path / "requirements-dev.lock"
    slash = chr(92)
    digest = "a" * 64
    path.write_text(
        f"pytest==9.1.1 {slash}\n"
        f"    --hash=sha256:{digest} {slash}\n"
        + trailing,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dangling line continuation"):
        read_hashed_versions(path)


def test_terminated_hash_option_remains_valid(tmp_path: Path) -> None:
    path = tmp_path / "requirements-dev.lock"
    slash = chr(92)
    digest = "a" * 64
    path.write_text(
        f"pytest==9.1.1 {slash}\n"
        f"    --hash=sha256:{digest}\n",
        encoding="utf-8",
    )
    assert read_hashed_versions(path) == {"pytest": "9.1.1"}
