"""Read-only integrity check for an existing GitHub Release's downloaded assets.

Usage: python scripts/verify_release_assets.py BUILT_DIST DOWNLOADED_RELEASE
Never writes to either directory and never calls GitHub or the network.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def _inventory(folder: Path) -> dict[str, Path] | None:
    """Require exactly one wheel, one sdist and one checksum manifest."""
    if folder.is_symlink() or not folder.is_dir():
        return None
    entries = list(folder.iterdir())
    if len(entries) != 3 or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        return None
    result = {entry.name: entry for entry in entries}
    names = set(result)
    if (
        len(result) != 3
        or sum(name.endswith(".whl") for name in names) != 1
        or sum(name.endswith(".tar.gz") for name in names) != 1
        or "SHA256SUMS" not in names
    ):
        return None
    return result


def _digest(path: Path) -> bytes:
    """Compare artifacts in bounded chunks, not as whole in-memory files."""
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            result.update(chunk)
    return result.digest()


def verify(built_dir: Path, published_dir: Path) -> list[str]:
    """Return fail-closed diagnostic codes without exposing artifact contents."""
    try:
        built = _inventory(built_dir)
        published = _inventory(published_dir)
        if built is None or published is None:
            return ["invalid_release_asset_inventory"]
        if built.keys() != published.keys():
            return ["different_release_asset_names"]
        for name in sorted(built):
            if _digest(built[name]) != _digest(published[name]):
                return ["different_release_asset_contents"]
    except OSError:
        return ["unreadable_release_asset"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("built_dir", type=Path)
    parser.add_argument("published_dir", type=Path)
    args = parser.parse_args(argv)
    failures = verify(args.built_dir, args.published_dir)
    for failure in failures:
        print(f"Release integrity failed: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("Existing release assets match exactly; no files will be replaced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
