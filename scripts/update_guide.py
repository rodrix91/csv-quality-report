"""Regenerate the outputs embedded in docs/guides/spanish-exports.md from real runs.

Every ``console`` block in the guide holds one command line starting with
``$ python -m csv_quality_report``; the ``markdown`` block right after it is
the report that command prints. ``tests/test_guide.py`` fails when they drift
apart, so run this after an intended change and review the diff:

    python scripts/update_guide.py          # rewrite the outputs
    python scripts/update_guide.py --check  # only report stale ones
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "guides" / "spanish-exports.md"
sys.path.insert(0, str(ROOT / "src"))

from csv_quality_report.cli import main as cli_main  # noqa: E402

PROMPT = "$ python -m csv_quality_report "
# A console block with one command, then the markdown block with its output.
SAMPLE_RE = re.compile(
    r"(```console\n\$ python -m csv_quality_report (?P<args>[^\n]*)\n```\n\n```markdown\n)"
    r"(?P<output>.*?)(```)",
    re.DOTALL,
)
REPORT_CODES = (0, 8)  # a report is printed; 8 means a quality gate failed


def run(args: list[str]) -> tuple[int, str]:
    """Run the command line from the repository root; return the exit code and stdout."""
    out = io.StringIO()
    previous = Path.cwd()
    os.chdir(ROOT)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli_main(args)
    finally:
        os.chdir(previous)
    return code, out.getvalue()


def samples(text: str) -> list[list[str]]:
    """The argument lists of every sample in ``text``, in order."""
    return [shlex.split(match["args"]) for match in SAMPLE_RE.finditer(text)]


def update(text: str) -> str:
    """``text`` with every sample output replaced by a fresh run."""

    def replace(match: re.Match[str]) -> str:
        code, output = run(shlex.split(match["args"]))
        if code not in REPORT_CODES:
            raise SystemExit(f"{PROMPT}{match['args']} exited with {code}")
        return match.group(1) + output + match.group(4)

    return SAMPLE_RE.sub(replace, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if outputs are stale")
    args = parser.parse_args()
    current = GUIDE.read_text(encoding="utf-8")
    updated = update(current)
    if updated == current:
        print("guide outputs are up to date")
        return 0
    if args.check:
        print("guide outputs are stale; run python scripts/update_guide.py")
        return 1
    GUIDE.write_text(updated, encoding="utf-8")
    print(f"guide outputs updated ({len(samples(updated))} samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
