"""Fail CI when declared development dependencies drift from the hashed lock."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;\\#]+)")


def read_versions(path: Path) -> dict[str, str]:
    """Read pinned requirements, ignoring hashes, comments and environment markers."""
    versions: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "--")):
            continue
        requirement = line.removesuffix("\\").strip().partition(";")[0].strip()
        match = _PIN.fullmatch(requirement)
        if match is None:
            raise ValueError(f"{path.name}:{number}: unsupported requirement {line!r}")
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        if name in versions:
            raise ValueError(f"{path.name}:{number}: duplicate dependency {name}")
        versions[name] = match.group(2)
    if not versions:
        raise ValueError(f"{path.name}: no pinned requirements found")
    return versions


_HASH = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}")


def read_hashed_versions(path: Path) -> dict[str, str]:
    """Read package pins and require a valid SHA-256 digest per lock entry.

    A version-only lock is not an installable --require-hashes lock. Validate
    *all* resolved packages, not only top-level development dependencies.
    """
    versions = read_versions(path)
    current: str | None = None
    has_hash = False
    # pip only attaches a --hash on a following physical line when the
    # preceding requirement or hash line ends in a backslash.
    continued = False
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line_continues = line.endswith("\\")
        entry = line.removesuffix("\\").strip()
        if entry.startswith("--"):
            if current is None:
                raise ValueError(f"{path.name}:{number}: hash without a package")
            if _HASH.fullmatch(entry) is None:
                raise ValueError(f"{path.name}:{number}: invalid SHA-256 hash option")
            if not continued:
                raise ValueError(f"{path.name}:{number}: hash has no line continuation")
            has_hash = True
            continued = line_continues
            continue
        if continued:
            raise ValueError(f"{path.name}:{number}: expected continued hash option")
        if current is not None and not has_hash:
            raise ValueError(f"{path.name}: package {current} lacks a SHA-256 hash")
        requirement = entry.partition(";")[0].strip()
        match = _PIN.fullmatch(requirement)
        if match is None:
            # In particular, never silently accept a new installer option.
            raise ValueError(f"{path.name}:{number}: unsupported lock entry {line!r}")
        current = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        has_hash = False
        continued = line_continues
    if current is not None and not has_hash:
        raise ValueError(f"{path.name}: package {current} lacks a SHA-256 hash")
    return versions


def check_versions(requirements: Path, lock: Path) -> list[str]:
    """Report direct pins absent from or out of sync with the hashed lock."""
    declared = read_versions(requirements)
    locked = read_hashed_versions(lock)
    return [
        f"{name}: requirements-dev.txt specifies {version}, lock has {locked.get(name, 'missing')}"
        for name, version in declared.items()
        if locked.get(name) != version
    ]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=root / "requirements-dev.txt")
    parser.add_argument("--lock", type=Path, default=root / "requirements-dev.lock")
    args = parser.parse_args()
    try:
        problems = check_versions(args.requirements, args.lock)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Dependency lock verification failed: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"Dependency lock verification failed: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("Development dependency pins match the hashed lock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
