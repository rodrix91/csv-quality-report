"""Offline regressions for immutable GitHub Release assets."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_release_assets", ROOT / "scripts" / "verify_release_assets.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load()
WHEEL = "csv_quality_report-0.24.0-py3-none-any.whl"
SDIST = "csv_quality_report-0.24.0.tar.gz"


def _make_release(folder: Path) -> None:
    folder.mkdir()
    files = {WHEEL: b"synthetic-wheel", SDIST: b"synthetic-sdist"}
    for name, contents in files.items():
        (folder / name).write_bytes(contents)
    manifest = "".join(
        f"{hashlib.sha256(contents).hexdigest()}  {name}\n"
        for name, contents in sorted(files.items())
    )
    (folder / "SHA256SUMS").write_text(manifest, encoding="ascii")


def test_identical_release_assets_are_safe_to_leave_untouched(tmp_path: Path) -> None:
    built, published = tmp_path / "built", tmp_path / "published"
    _make_release(built)
    _make_release(published)
    assert release.verify(built, published) == []


@pytest.mark.parametrize("name", [WHEEL, SDIST, "SHA256SUMS"])
def test_changed_published_asset_is_rejected(tmp_path: Path, name: str) -> None:
    built, published = tmp_path / "built", tmp_path / "published"
    _make_release(built)
    _make_release(published)
    (published / name).write_bytes(b"changed-published-artifact")
    assert release.verify(built, published) == ["different_release_asset_contents"]


@pytest.mark.parametrize("remove_from", ["built", "published"])
def test_missing_release_asset_is_rejected(tmp_path: Path, remove_from: str) -> None:
    built, published = tmp_path / "built", tmp_path / "published"
    _make_release(built)
    _make_release(published)
    ((built if remove_from == "built" else published) / WHEEL).unlink()
    assert release.verify(built, published) == ["invalid_release_asset_inventory"]


def test_unexpected_extra_asset_is_rejected(tmp_path: Path) -> None:
    built, published = tmp_path / "built", tmp_path / "published"
    _make_release(built)
    _make_release(published)
    (published / "extra.txt").write_text("unexpected")
    assert release.verify(built, published) == ["invalid_release_asset_inventory"]


def test_missing_release_directory_is_rejected(tmp_path: Path) -> None:
    built, published = tmp_path / "built", tmp_path / "missing"
    _make_release(built)
    assert release.verify(built, published) == ["invalid_release_asset_inventory"]


def test_symlinked_artifact_is_rejected(tmp_path: Path) -> None:
    built, published = tmp_path / "built", tmp_path / "published"
    _make_release(built)
    _make_release(published)
    (published / WHEEL).unlink()
    try:
        (published / WHEEL).symlink_to(built / WHEEL)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this runner")
    assert release.verify(built, published) == ["invalid_release_asset_inventory"]


def test_read_only_cli_rejects_mismatched_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, published = tmp_path / "built", tmp_path / "published"
    _make_release(built)
    _make_release(published)
    assert release.main([str(built), str(published)]) == 0
    assert "no files will be replaced" in capsys.readouterr().out
    (published / SDIST).write_bytes(b"tampered")
    assert release.main([str(built), str(published)]) == 1
    assert "different_release_asset_contents" in capsys.readouterr().err


def test_expected_asset_names_are_required(tmp_path: Path) -> None:
    built, published = tmp_path / "built", tmp_path / "published"
    _make_release(built)
    _make_release(published)
    (published / WHEEL).rename(published / "alternate-version.whl")
    assert release.verify(built, published) == ["different_release_asset_names"]


def test_release_verification_only_reads_files(tmp_path: Path) -> None:
    built, published = tmp_path / "built", tmp_path / "published"
    _make_release(built)
    _make_release(published)
    original = {p.name: p.read_bytes() for p in published.iterdir()}
    assert release.verify(built, published) == []
    assert {p.name: p.read_bytes() for p in published.iterdir()} == original
