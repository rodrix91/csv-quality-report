"""The reusable Action must not advertise an unchanged JSON report as fresh."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.report_freshness import fresh_report, main, report_fingerprint


def test_missing_and_nonregular_report_are_not_fresh(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    assert report_fingerprint(missing) == "missing"
    assert not fresh_report("missing", "missing")
    assert report_fingerprint(tmp_path) == "not-file"
    assert not fresh_report("missing", "not-file")


def test_an_unchanged_old_report_is_not_new(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"rows": 999}\n', encoding="utf-8")
    before = report_fingerprint(report)
    assert before.startswith("file:")
    assert report_fingerprint(report) == before
    assert not fresh_report(before, report_fingerprint(report))


def test_new_report_and_atomic_replacement_are_fresh(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    original = report_fingerprint(report)
    report.write_text('{"rows": 3}\n', encoding="utf-8")
    created = report_fingerprint(report)
    assert fresh_report(original, created)

    replacement = tmp_path / "pending.json"
    replacement.write_text('{"rows": 3}\n', encoding="utf-8")
    os.replace(replacement, report)
    replaced = report_fingerprint(report)
    assert fresh_report(created, replaced)


def test_changed_in_place_report_metadata_is_detected(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("old", encoding="utf-8")
    os.utime(report, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    before = report_fingerprint(report)
    report.write_text("updated", encoding="utf-8")
    os.utime(report, ns=(1_700_000_010_000_000_000, 1_700_000_010_000_000_000))
    assert fresh_report(before, report_fingerprint(report))


def test_report_fingerprint_does_not_read_sensitive_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "private.json"
    report.write_text('{"secret": "do-not-print"}\n', encoding="utf-8")

    def fail_read(_self: Path, *_args: object, **_kwargs: object) -> str:
        raise AssertionError("Report content must not be read")

    monkeypatch.setattr(Path, "read_text", fail_read)
    signature = report_fingerprint(report)
    assert "secret" not in signature


def test_script_reports_current_fingerprint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "report.json"
    report.write_text("{}\n", encoding="utf-8")
    assert main([str(report)]) == 0
    assert capsys.readouterr().out.strip() == report_fingerprint(report)


def test_script_rejects_bad_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err


def test_script_fails_closed_on_stat_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def deny(_self: Path) -> os.stat_result:
        raise PermissionError("private path: do-not-print")

    monkeypatch.setattr(Path, "stat", deny)
    assert main(["secret.json"]) == 3
    error = capsys.readouterr().err
    assert "Cannot inspect JSON report" in error
    assert "do-not-print" not in error
