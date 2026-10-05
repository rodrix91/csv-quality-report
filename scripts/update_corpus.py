"""Regenerate the expected reports of the end-to-end corpus in tests/corpus.

Each case in ``tests/corpus/cases.json`` runs the command line on one file
with its options; the JSON report it prints is stored in
``tests/corpus/expected/<name>.json``. Cases that stop with an error (any
exit code other than 0, or 8 for failed quality gates, which still print
the report) store the message written to stderr in
``tests/corpus/expected/<name>.txt`` instead. ``tests/test_corpus.py`` fails when
the output drifts, so run this after an intended change and review the diff:

    python scripts/update_corpus.py          # rewrite the expected files
    python scripts/update_corpus.py --check  # only report stale ones
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(ROOT / "src"))

from csv_quality_report.cli import main as cli_main  # noqa: E402
from csv_quality_report.errors import EXIT_CHECKS  # noqa: E402

REPORT_CODES = (0, EXIT_CHECKS)  # exit codes that come with a report on stdout


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads((CORPUS / "cases.json").read_text(encoding="utf-8"))
    return cases


def run_case(case: dict[str, Any]) -> tuple[int, str]:
    """Run one case from the repository root (stable relative paths).

    Returns the exit code and the JSON report, or the error message when the
    exit code means that no report was produced.
    """
    out, err = io.StringIO(), io.StringIO()
    previous = Path.cwd()
    os.chdir(ROOT)
    try:
        path = str(Path("tests") / "corpus" / case["file"])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli_main([path, "--format", "json", *case["args"]])
    finally:
        os.chdir(previous)
    return code, out.getvalue() if code in REPORT_CODES else err.getvalue()


def expected_path(case: dict[str, Any]) -> Path:
    suffix = ".json" if case["exit_code"] in REPORT_CODES else ".txt"
    return CORPUS / "expected" / f"{case['name']}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if any expected file is stale")
    args = parser.parse_args()
    stale = []
    for case in load_cases():
        code, output = run_case(case)
        if code != case["exit_code"]:
            print(f"{case['name']}: exit code {code}, expected {case['exit_code']}")
            return 1
        target = expected_path(case)
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current != output:
            stale.append(case["name"])
            if not args.check:
                target.write_text(output, encoding="utf-8")
    if args.check and stale:
        print("stale expected reports: " + ", ".join(stale))
        return 1
    print("updated: " + ", ".join(stale) if stale else "corpus expected reports are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
