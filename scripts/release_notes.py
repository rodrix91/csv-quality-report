"""Print the CHANGELOG section of one version, for the notes of its GitHub release.

    python scripts/release_notes.py 0.9.0

The section is everything between ``## [0.9.0] - <date>`` and the next
``## [`` heading, without the heading itself, followed by a link to the
full changelog. Exits with status 1 when the version has no section, so a
release is never published with empty notes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
FULL_CHANGELOG = "https://github.com/rodrix91/csv-quality-report/blob/main/CHANGELOG.md"


def section(text: str, version: str) -> str | None:
    """The body of the ``version`` section of ``text``, stripped, or ``None``."""
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    match = heading.search(text)
    if match is None:
        return None
    following = re.compile(r"^## \[", re.MULTILINE).search(text, match.end())
    end = following.start() if following else len(text)
    # Link definitions at the bottom ("[0.9.0]: https://...") are not notes.
    body = re.sub(r"^\[[^\]]+\]: \S+\n?", "", text[match.end() : end], flags=re.MULTILINE)
    return body.strip() or None


def notes(text: str, version: str) -> str | None:
    """Release notes for ``version``: its section and a link to the full changelog."""
    body = section(text, version)
    return None if body is None else f"{body}\n\nFull changelog: {FULL_CHANGELOG}\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python scripts/release_notes.py VERSION", file=sys.stderr)
        return 2
    version = args[0].removeprefix("v")
    result = notes(CHANGELOG.read_text(encoding="utf-8"), version)
    if result is None:
        print(f"CHANGELOG.md has no section for {version}", file=sys.stderr)
        return 1
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
