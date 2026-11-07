"""Reject wrong Python argument types at public clock boundaries predictably."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from csv_quality_report.clock import current_time, format_stamp, parse_stamp


class UnsafeRepresentation:
    def __repr__(self) -> str:
        raise AssertionError("must not call repr on untrusted clock values")


@pytest.mark.parametrize(
    "invalid",
    [None, False, True, 0, 1.5, b"0", [], {}, UnsafeRepresentation()],
)
def test_injected_epoch_mapping_rejects_nontext_values_without_echo(invalid: object) -> None:
    with pytest.raises(
        ValueError, match="invalid SOURCE_DATE_EPOCH: value must be a string"
    ) as exc:
        current_time({"SOURCE_DATE_EPOCH": cast(str, invalid)})
    assert len(str(exc.value)) < 100


@pytest.mark.parametrize("invalid", [None, 0, False, "2026-10-07", [], {}])
def test_format_stamp_rejects_non_datetime_values_with_existing_message(invalid: object) -> None:
    with pytest.raises(ValueError, match="moment must be an aware datetime"):
        format_stamp(cast(datetime, invalid))


@pytest.mark.parametrize(
    "invalid", [None, 0, True, 1.5, b"2026-10-07T00:00:00Z", [], {}, UnsafeRepresentation()]
)
def test_parse_stamp_returns_none_for_nontext_inputs(invalid: object) -> None:
    assert parse_stamp(cast(str, invalid)) is None


def test_correct_utc_inputs_keep_their_exact_results() -> None:
    expected = datetime(2026, 10, 7, tzinfo=UTC)
    assert current_time({"SOURCE_DATE_EPOCH": "1791331200"}) == expected
    assert format_stamp(expected) == "2026-10-07T00:00:00Z"
    assert parse_stamp("2026-10-07T00:00:00Z") == expected
    assert parse_stamp("2026-02-30T00:00:00Z") is None
