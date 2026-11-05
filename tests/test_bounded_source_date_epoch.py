"""Resource-bounded, non-disclosing SOURCE_DATE_EPOCH parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from csv_quality_report.cli import main
from csv_quality_report.clock import current_time


def test_epoch_exact_length_limit_retains_leading_zeroes() -> None:
    # Padding has always been valid because SOURCE_DATE_EPOCH is decimal text.
    value = "0" * 64
    assert current_time({"SOURCE_DATE_EPOCH": value}) == datetime(1970, 1, 1, tzinfo=UTC)
    padded = "0" * (64 - len("1791331200")) + "1791331200"
    assert current_time({"SOURCE_DATE_EPOCH": padded}) == datetime(2026, 10, 7, tzinfo=UTC)


@pytest.mark.parametrize(
    "malformed",
    [
        "9" * 65,
        "0" * 100_000,
        "secret-value" * 10_000,
    ],
    ids=["65-digit-epoch", "100k-digit-epoch", "100k-text-epoch"],
)
def test_oversized_epoch_is_rejected_without_echoing_input(malformed: str) -> None:
    with pytest.raises(ValueError, match="SOURCE_DATE_EPOCH: value exceeds 64 characters") as exc:
        current_time({"SOURCE_DATE_EPOCH": malformed})
    message = str(exc.value)
    assert len(message) < 100
    assert "secret-value" not in message
    assert "99999999" not in message


def test_existing_short_invalid_syntax_and_range_diagnostics_are_preserved() -> None:
    with pytest.raises(ValueError, match="a whole number of seconds"):
        current_time({"SOURCE_DATE_EPOCH": "tomorrow"})
    with pytest.raises(ValueError, match="out of range"):
        current_time({"SOURCE_DATE_EPOCH": "9" * 30})


def test_cli_rejects_oversized_epoch_before_reading_or_overwriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    existing_report = tmp_path / "previous-report.json"
    original = '{"verified":true}\n'
    existing_report.write_text(original, encoding="utf-8")
    # The missing input must not be opened; clock validation happens first.
    missing_csv = tmp_path / "missing.csv"
    # Windows limits a single environment value to 32,767 characters.
    # The direct API tests above still exercise 100,000-character inputs.
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "secret-token" * 1_000)

    with pytest.raises(SystemExit) as raised:
        main(
            [
                str(missing_csv),
                "--record-time",
                "--format",
                "json",
                "--json-output",
                str(existing_report),
            ]
        )
    assert raised.value.code == 2
    result = capsys.readouterr()
    assert "SOURCE_DATE_EPOCH: value exceeds 64 characters" in result.err
    assert "secret-token" not in result.err
    assert "missing.csv" not in result.err
    assert result.out == ""
    assert existing_report.read_text(encoding="utf-8") == original
