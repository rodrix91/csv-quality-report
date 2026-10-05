"""End-to-end corpus: realistic files, their options, and the exact JSON reports.

The expected reports live in ``tests/corpus/expected``; regenerate them with
``python scripts/update_corpus.py`` after an intended change and review the diff.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "update_corpus", ROOT / "scripts" / "update_corpus.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corpus = _load_script()
CASES: list[dict[str, Any]] = corpus.load_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_corpus_case(case: dict[str, Any]) -> None:
    code, output = corpus.run_case(case)
    assert code == case["exit_code"], case["about"]
    expected = corpus.expected_path(case).read_text(encoding="utf-8")
    assert output == expected, (
        f"{case['name']} changed; if intended, run python scripts/update_corpus.py "
        "and review the diff"
    )


def test_every_corpus_file_is_used() -> None:
    files = {p.name for p in (ROOT / "tests" / "corpus").iterdir() if p.is_file()}
    used = {c["file"] for c in CASES} | {"cases.json", "README.md"}
    assert files <= used, files - used


def test_every_expected_report_belongs_to_a_case() -> None:
    names = {c["name"] for c in CASES}
    expected = {p.stem for p in (ROOT / "tests" / "corpus" / "expected").glob("*.json")}
    assert expected == names


def test_reports_are_valid_json_with_relative_sources() -> None:
    for case in CASES:
        report = json.loads(corpus.expected_path(case).read_text(encoding="utf-8"))
        assert report["source"] == f"tests/corpus/{case['file']}"
