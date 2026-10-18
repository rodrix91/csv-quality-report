"""Regenerate the outputs embedded in docs/guides/spanish-exports.md from real runs.

Every ``console`` block in the guide holds one command line starting with
``$ python -m csv_quality_report``, optionally after ``NAME=value``
environment assignments (``$ SOURCE_DATE_EPOCH=1791806400 python -m ...``,
for a fixed clock); the ``markdown`` block right after it is the report that
command prints. ``tests/test_guide.py`` fails when they drift
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
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "guides" / "spanish-exports.md"
sys.path.insert(0, str(ROOT / "src"))

from csv_quality_report.cli import main as cli_main  # noqa: E402

PROMPT = "$ python -m csv_quality_report "
# A console block with one command, then the markdown block with its output.
# Words before ``python`` are environment assignments, checked by environment().
SAMPLE_RE = re.compile(
    r"(?P<head>```console\n\$ (?P<env>(?:[^ \n]+ )*?)python -m csv_quality_report "
    r"(?P<args>[^\n]*)\n```\n\n```markdown\n)"
    r"(?P<output>.*?)(?P<tail>```)",
    re.DOTALL,
)
REPORT_CODES = (0, 8)  # a report is printed; 8 means a quality gate failed


def environment(text: str) -> dict[str, str]:
    """The ``NAME=value`` assignments before a sample's command, in order."""
    assignments: dict[str, str] = {}
    for word in text.split():
        name, sep, value = word.partition("=")
        if not sep or re.fullmatch(r"[A-Z_][A-Z0-9_]*", name) is None:
            raise ValueError(f"not an environment assignment: {word!r}")
        assignments[name] = value
    return assignments


@contextlib.contextmanager
def _environ(assignments: dict[str, str]) -> Iterator[None]:
    """Set ``assignments`` in ``os.environ`` and restore the previous values after."""
    previous = {name: os.environ.get(name) for name in assignments}
    os.environ.update(assignments)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                del os.environ[name]
            else:
                os.environ[name] = value


def run(args: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run the command line from the repository root; return the exit code and stdout.

    ``env`` holds environment variables set only while the command runs.
    """
    out = io.StringIO()
    previous = Path.cwd()
    os.chdir(ROOT)
    try:
        with (
            _environ(env or {}),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(io.StringIO()),
        ):
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
        code, output = run(shlex.split(match["args"]), environment(match["env"]))
        if code not in REPORT_CODES:
            raise SystemExit(f"{PROMPT}{match['args']} exited with {code}")
        return match["head"] + output + match["tail"]

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
