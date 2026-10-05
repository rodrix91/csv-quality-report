"""The version is declared twice; keep both in sync and expose it on the CLI."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from csv_quality_report import __version__
from csv_quality_report.cli import main

ROOT = Path(__file__).resolve().parent.parent


def test_package_version_matches_pyproject() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        assert tomllib.load(handle)["project"]["version"] == __version__


def test_changelog_has_an_entry_for_the_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(
        rf"^## \[{re.escape(__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M
    )


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"csv-quality-report {__version__}"
