"""Regression tests for deterministic development dependency lock validation."""

from pathlib import Path

import pytest

from scripts.check_dev_lock import check_versions, read_versions


def test_matches_pins_and_ignores_transitive_hashes_and_markers(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    lock = tmp_path / "requirements-dev.lock"
    requirements.write_text("# Direct pins\npytest==9.1.1\nruff==0.17.1\n", encoding="utf-8")
    lock.write_text(
        "pytest==9.1.1 \\\n"
        "    --hash=sha256:abc\n"
        "ruff==0.17.1 \\\n"
        "    --hash=sha256:def\n"
        "colorama==0.4.6 ; os_name == 'nt' \\\n"
        "    --hash=sha256:ghi\n",
        encoding="utf-8",
    )
    assert check_versions(requirements, lock) == []


def test_rejects_stale_and_missing_direct_pins(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    lock = tmp_path / "requirements-dev.lock"
    requirements.write_text("ruff==0.17.2\nmypy==2.4.0\n", encoding="utf-8")
    lock.write_text("ruff==0.17.1 \\\n    --hash=sha256:abc\n", encoding="utf-8")
    assert check_versions(requirements, lock) == [
        "ruff: requirements-dev.txt specifies 0.17.2, lock has 0.17.1",
        "mypy: requirements-dev.txt specifies 2.4.0, lock has missing",
    ]


def test_rejects_duplicate_canonicalized_dependency_name(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    requirements.write_text("my_pkg==1.0\nmy-pkg==1.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate dependency my-pkg"):
        read_versions(requirements)


def test_rejects_unpinned_or_empty_requirements(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    requirements.write_text("ruff>=0.17\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported requirement"):
        read_versions(requirements)
    requirements.write_text("# No dependencies\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no pinned requirements"):
        read_versions(requirements)
