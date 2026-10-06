"""The documented Python API (issue #22): exports, and the README example runs as shown."""

from __future__ import annotations

import contextlib
import io
import os
import re
from pathlib import Path

import pytest

import csv_quality_report
from csv_quality_report import checks, compare, errors, profile, reader, render

ROOT = Path(__file__).resolve().parent.parent


def test_public_names_are_exported_and_listed() -> None:
    expected = {
        "CheckResult",
        "ColumnProfile",
        "Comparison",
        "CsvQualityError",
        "Report",
        "__version__",
        "build_report",
        "compare_reports",
        "evaluate",
        "profile_file",
        "read_table",
        "render_json",
        "render_markdown",
    }
    assert set(csv_quality_report.__all__) == expected
    for name in expected:
        assert hasattr(csv_quality_report, name), name


def test_exports_are_the_same_objects_as_the_module_paths() -> None:
    # Existing imports such as csv_quality_report.profile.profile_file keep working.
    assert csv_quality_report.profile_file is profile.profile_file
    assert csv_quality_report.build_report is profile.build_report
    assert csv_quality_report.read_table is reader.read_table
    assert csv_quality_report.evaluate is checks.evaluate
    assert csv_quality_report.render_json is render.render_json
    assert csv_quality_report.render_markdown is render.render_markdown
    assert csv_quality_report.compare_reports is compare.compare_reports
    assert csv_quality_report.Comparison is compare.Comparison
    assert csv_quality_report.CsvQualityError is errors.CsvQualityError


def _readme_example() -> tuple[str, str]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Use from Python\n", 1)[1].split("\n## ", 1)[0]
    code = re.search(r"```python\n(.*?)```", section, re.DOTALL)
    output = re.search(r"it prints:\n\n```text\n(.*?)```", section, re.DOTALL)
    assert code and output, "README 'Use from Python' section changed shape"
    return code.group(1), output.group(1)


def test_readme_example_runs_and_prints_what_the_readme_shows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, expected = _readme_example()
    monkeypatch.chdir(ROOT)
    buffer = io.StringIO()
    namespace: dict[str, object] = {}
    with contextlib.redirect_stdout(buffer):
        exec(compile(code, "README.md", "exec"), namespace)
    assert buffer.getvalue() == expected
    json_text = namespace["json_text"]
    assert isinstance(json_text, str) and '"checks": [' in json_text
    assert os.getcwd() == str(ROOT)
