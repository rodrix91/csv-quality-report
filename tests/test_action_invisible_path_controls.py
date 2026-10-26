"""GitHub Action path validators reject invisible terminal controls before use."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


@pytest.mark.parametrize(
    ("script", "kind"),
    [
        ("validate_action_read_path.py", "path"),
        ("validate_action_read_path.py", "baseline"),
        ("validate_action_report_path.py", None),
    ],
)
@pytest.mark.parametrize("control", ["\t", "\x01", "\x07", "\x1b", "\x7f", "\x85", "\x9f"])
def test_invisible_path_controls_are_rejected(
    script: str, kind: str | None, control: str, tmp_path: Path
) -> None:
    args = [sys.executable, str(SCRIPTS / script), f"export{control}file.csv", str(tmp_path)]
    if kind is not None:
        args.append(kind)
    completed = subprocess.run(args, text=True, capture_output=True, check=False)
    assert completed.returncode == 2
    assert "terminal control characters" in completed.stderr


@pytest.mark.parametrize("control", ["\n", "\r"])
def test_report_validator_refuses_line_breaks(control: str, tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "validate_action_report_path.py"),
            f"reports/output{control}file.json",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "line breaks" in completed.stderr


@pytest.mark.parametrize(
    ("script", "kind"),
    [
        ("validate_action_read_path.py", "path"),
        ("validate_action_read_path.py", "baseline"),
        ("validate_action_report_path.py", None),
    ],
)
def test_normal_unicode_workspace_paths_remain_valid(
    script: str, kind: str | None, tmp_path: Path
) -> None:
    args = [sys.executable, str(SCRIPTS / script), "reports/año-高.csv", str(tmp_path)]
    if kind is not None:
        args.append(kind)
    completed = subprocess.run(args, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
