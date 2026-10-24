"""Regression tests for GitHub Action CSV and baseline read boundaries."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate_action_read_path.py"


def validate(path: str, workspace: Path, kind: str = "path") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), path, str(workspace), kind],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("kind", ["path", "baseline"])
def test_nested_workspace_path_is_valid(tmp_path: Path, kind: str) -> None:
    directory = tmp_path / "exports"
    directory.mkdir()
    (directory / "data.csv").write_text("id\n1\n", encoding="utf-8")
    assert validate("exports/data.csv", tmp_path, kind).returncode == 0
    assert validate("exports/../exports/data.csv", tmp_path, kind).returncode == 0


def test_missing_relative_baseline_is_allowed_for_skip_mode(tmp_path: Path) -> None:
    assert validate("reports/yesterday.json", tmp_path, "baseline").returncode == 0


@pytest.mark.parametrize("kind", ["path", "baseline"])
def test_absolute_paths_are_rejected(tmp_path: Path, kind: str) -> None:
    result = validate(str(tmp_path / "data.csv"), tmp_path, kind)
    assert result.returncode == 2
    assert "must be relative" in result.stderr


@pytest.mark.parametrize("kind", ["path", "baseline"])
def test_parent_escape_is_rejected(tmp_path: Path, kind: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = validate("../secret.csv", workspace, kind)
    assert result.returncode == 2
    assert "must stay within" in result.stderr


@pytest.mark.parametrize("kind", ["path", "baseline"])
def test_symlink_escape_is_rejected(tmp_path: Path, kind: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.csv"
    outside.write_text("private\n", encoding="utf-8")
    link = workspace / "alias.csv"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this runner")
    result = validate("alias.csv", workspace, kind)
    assert result.returncode == 2
    assert "must stay within" in result.stderr


@pytest.mark.parametrize("value", ["", "-", "data\n.csv", "data\r.csv"])
def test_invalid_input_names_fail_closed(tmp_path: Path, value: str) -> None:
    assert validate(value, tmp_path).returncode == 2


def test_unknown_kind_is_rejected(tmp_path: Path) -> None:
    result = validate("data.csv", tmp_path, "report")
    assert result.returncode == 2
    assert "path kind" in result.stderr


def test_validator_requires_three_arguments() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr
