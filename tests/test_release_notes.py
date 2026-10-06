"""Tests for scripts/release_notes.py, used by the release workflow."""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_notes", ROOT / "scripts" / "release_notes.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rn = _load_script()
SAMPLE = """# Changelog

## [Unreleased]

## [1.1.0] - 2026-10-06

### Added

- Second thing (#2).

## [1.0.0] - 2026-10-05

- First release.

[Unreleased]: https://example.com/compare/v1.1.0...HEAD
[1.1.0]: https://example.com/compare/v1.0.0...v1.1.0
"""


def test_section_is_the_body_between_headings() -> None:
    assert rn.section(SAMPLE, "1.1.0") == "### Added\n\n- Second thing (#2)."


def test_last_section_drops_the_link_definitions() -> None:
    assert rn.section(SAMPLE, "1.0.0") == "- First release."


def test_missing_or_empty_sections() -> None:
    assert rn.section(SAMPLE, "2.0.0") is None
    assert rn.section(SAMPLE, "Unreleased") is None  # empty: never published
    assert rn.section(SAMPLE, "1.1") is None  # no prefix matches


def test_notes_end_with_the_full_changelog_link() -> None:
    assert rn.notes(SAMPLE, "1.0.0") == f"- First release.\n\nFull changelog: {rn.FULL_CHANGELOG}\n"
    assert rn.notes(SAMPLE, "9.9.9") is None


def test_every_released_version_of_the_real_changelog_has_notes() -> None:
    text = rn.CHANGELOG.read_text(encoding="utf-8")
    versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.MULTILINE)
    assert "0.1.0" in versions
    for version in versions:
        notes = rn.notes(text, version)
        assert notes is not None and "## [" not in notes, version


def test_the_current_version_has_notes() -> None:
    # The release workflow fails when the tagged version has no section.
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    assert rn.notes(rn.CHANGELOG.read_text(encoding="utf-8"), version) is not None


def test_main(capsys: pytest.CaptureFixture[str]) -> None:
    assert rn.main(["v0.9.0"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("### Added\n") and out.endswith(f"Full changelog: {rn.FULL_CHANGELOG}\n")
    assert rn.main(["9.9.9"]) == 1
    assert capsys.readouterr().err == "CHANGELOG.md has no section for 9.9.9\n"
    assert rn.main([]) == 2
    assert "usage:" in capsys.readouterr().err
