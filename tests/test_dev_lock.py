"""Regression tests for deterministic development dependency lock validation."""

from pathlib import Path

import pytest

from scripts.check_dev_lock import check_versions, read_hashed_versions, read_versions


def test_matches_pins_and_ignores_transitive_hashes_and_markers(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    lock = tmp_path / "requirements-dev.lock"
    requirements.write_text("# Direct pins\npytest==9.1.1\nruff==0.17.1\n", encoding="utf-8")
    slash = chr(92)
    digest_a, digest_b, digest_c = "a" * 64, "b" * 64, "c" * 64
    lock.write_text(
        f"pytest==9.1.1 {slash}\n"
        f"    --hash=sha256:{digest_a}\n"
        f"ruff==0.17.1 {slash}\n"
        f"    --hash=sha256:{digest_b}\n"
        f"colorama==0.4.6 ; os_name == 'nt' {slash}\n"
        f"    --hash=sha256:{digest_c}\n",
        encoding="utf-8",
    )
    assert check_versions(requirements, lock) == []


def test_rejects_stale_and_missing_direct_pins(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    lock = tmp_path / "requirements-dev.lock"
    requirements.write_text("ruff==0.17.2\nmypy==2.4.0\n", encoding="utf-8")
    digest = "a" * 64
    slash = chr(92)
    lock.write_text(f"ruff==0.17.1 {slash}\n    --hash=sha256:{digest}\n", encoding="utf-8")
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


def test_rejects_version_only_lock_even_when_all_versions_match(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    lock = tmp_path / "requirements-dev.lock"
    requirements.write_text("pytest==9.1.1\n", encoding="utf-8")
    lock.write_text("pytest==9.1.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pytest lacks a SHA-256 hash"):
        check_versions(requirements, lock)


@pytest.mark.parametrize(
    "lines, error",
    [
        ("pytest==9.1.1\n    --hash=sha256:abc\n", "invalid SHA-256 hash option"),
        ("--hash=sha256:" + "a" * 64 + "\npytest==9.1.1\n", "hash without a package"),
        ("pytest==9.1.1\n    --index-url=https://invalid.example\n", "invalid SHA-256 hash option"),
        (
            "pytest==9.1.1 " + chr(92) + "\n    --hash=sha256:" + "a" * 64 + "\nruff==0.17.2\n",
            "ruff lacks a SHA-256 hash",
        ),
    ],
)
def test_rejects_malformed_or_unhashed_lock_entries(tmp_path: Path, lines: str, error: str) -> None:
    lock = tmp_path / "requirements-dev.lock"
    lock.write_text(lines, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        read_hashed_versions(lock)


def test_hash_options_require_physical_line_continuations(tmp_path: Path) -> None:
    lock = tmp_path / "requirements-dev.lock"
    slash = chr(92)
    digest_a, digest_b = "a" * 64, "b" * 64
    invalid = [
        # pip silently ignores a hash when the requirement lacks a backslash.
        (f"pytest==9.1.1\n    --hash=sha256:{digest_a}\n", "hash has no line continuation"),
        # An extra hash is orphaned if the preceding hash line does not continue.
        (
            f"pytest==9.1.1 {slash}\n    --hash=sha256:{digest_a}\n"
            f"    --hash=sha256:{digest_b}\n",
            "hash has no line continuation",
        ),
        # A new requirement after a dangling backslash would be concatenated.
        (
            f"pytest==9.1.1 {slash}\nruff==0.17.2 {slash}\n"
            f"    --hash=sha256:{digest_a}\n",
            "expected continued hash option",
        ),
    ]
    for content, expected in invalid:
        lock.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match=expected):
            read_hashed_versions(lock)

    # Valid multi-hash requirements continue every line but the last.
    lock.write_text(
        f"pytest==9.1.1 {slash}\n"
        f"    --hash=sha256:{digest_a} {slash}\n"
        f"    --hash=sha256:{digest_b}\n",
        encoding="utf-8",
    )
    assert read_hashed_versions(lock) == {"pytest": "9.1.1"}


def test_hashed_lock_accepts_markers_and_transitive_dependencies(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements-dev.txt"
    lock = tmp_path / "requirements-dev.lock"
    requirements.write_text("pytest==9.1.1\n", encoding="utf-8")
    digest = "a" * 64
    slash = chr(92)
    lock.write_text(
        "# uv-generated hashed universal lock\n"
        f"colorama==0.4.6 ; os_name == 'nt' {slash}\n    --hash=sha256:{digest}\n"
        "    # via pytest\n"
        f"pytest==9.1.1 {slash}\n    --hash=sha256:{digest}\n"
        "    # via -r requirements-dev.txt\n",
        encoding="utf-8",
    )
    assert check_versions(requirements, lock) == []
