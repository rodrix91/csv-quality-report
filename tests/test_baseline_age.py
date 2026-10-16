"""Tests for ``--record-time`` and ``--max-baseline-age`` (issue #129)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from csv_quality_report import Comparison, compare_reports
from csv_quality_report.checks import (
    CHECK_BASELINE_AGE,
    CLOCK_SKEW_TOLERANCE,
    baseline_age_check,
    format_duration,
)
from csv_quality_report.cli import main
from csv_quality_report.clock import current_time, format_stamp, parse_stamp
from csv_quality_report.profile import profile_file

WriteCsv = Callable[..., Path]
DATA = "id,peso\n1,3\n2,4\n"
EPOCH = 1_791_331_200  # 2026-10-07T00:00:00Z
STAMP = "2026-10-07T00:00:00Z"
DAY = 86_400
GENERATED = datetime(2026, 10, 7, tzinfo=UTC)


def stamped(stamp: str | None = STAMP) -> Comparison:
    """A comparison whose baseline carries ``stamp`` (``None``: no stamp)."""
    return Comparison("x.csv", 2, 2, (), (), (), (), (), stamp)


# --- the clock -------------------------------------------------------------


def test_current_time_is_utc_in_whole_seconds() -> None:
    now = current_time({})
    assert now.tzinfo is UTC and now.microsecond == 0
    assert abs(datetime.now(UTC) - now) < timedelta(minutes=1)
    assert current_time({"SOURCE_DATE_EPOCH": ""}).tzinfo is UTC  # empty counts as unset


def test_source_date_epoch_replaces_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    assert current_time({"SOURCE_DATE_EPOCH": str(EPOCH)}) == GENERATED
    assert current_time({"SOURCE_DATE_EPOCH": "0"}) == datetime(1970, 1, 1, tzinfo=UTC)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    assert current_time() == GENERATED  # os.environ by default


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("abc", "a whole number of seconds"),
        ("-1", "a whole number of seconds"),
        ("1.5", "a whole number of seconds"),
        (" 5", "a whole number of seconds"),
        ("５", "a whole number of seconds"),  # a full-width digit, which int() accepts
        ("9" * 30, "out of range"),
    ],
)
def test_invalid_source_date_epoch(value: str, why: str) -> None:
    with pytest.raises(ValueError, match=f"invalid SOURCE_DATE_EPOCH: .* \\({why}"):
        current_time({"SOURCE_DATE_EPOCH": value})


def test_stamps_round_trip() -> None:
    assert format_stamp(GENERATED) == STAMP
    assert parse_stamp(STAMP) == GENERATED
    # Other offsets are converted to UTC; early years keep four digits.
    la_paz = timezone(timedelta(hours=-4))
    assert format_stamp(datetime(2026, 10, 6, 20, 0, 5, 999, tzinfo=la_paz)) == (
        "2026-10-07T00:00:05Z"
    )
    assert format_stamp(datetime(5, 1, 2, 3, 4, 5, tzinfo=UTC)) == "0005-01-02T03:04:05Z"


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-07T00:00:00",  # no Z
        "2026-10-07T00:00:00z",
        "2026-10-07T00:00:00+00:00",
        "2026-10-07T00:00:00.5Z",
        "2026-10-07 00:00:00Z",
        "2026-02-30T00:00:00Z",  # no such day
        "2026-10-07T24:00:00Z",
        " 2026-10-07T00:00:00Z",
        "2026-10-07T00:00:00Z\n",
        "２026-10-07T00:00:00Z",
    ],
)
def test_other_forms_are_not_stamps(text: str) -> None:
    assert parse_stamp(text) is None


@pytest.mark.parametrize(
    ("seconds", "words"),
    [
        (0, "0 seconds"),
        (1, "1 second"),
        (61, "1 minute 1 second"),
        (5400, "1 hour 30 minutes"),
        (7 * DAY, "7 days"),
        (9 * DAY + 4 * 3600, "9 days 4 hours"),
        (DAY + 3600 + 60 + 1, "1 day 1 hour 1 minute 1 second"),
        (2 * DAY + 2, "2 days 2 seconds"),
    ],
)
def test_format_duration(seconds: int, words: str) -> None:
    assert format_duration(seconds) == words


# --- the check -------------------------------------------------------------


def test_the_stamp_reaches_the_comparison(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA))

    def stamp_of(**extra: Any) -> str | None:
        return compare_reports({"rows": 2, "columns": [], **extra}, report).baseline_generated_at

    assert stamp_of(generated_at=STAMP) == STAMP
    assert stamp_of() is None
    assert stamp_of(generated_at=None) is None
    assert stamp_of(generated_at=1791331200) == "1791331200"  # kept as JSON text
    assert stamp_of(generated_at=["x"]) == '["x"]'


def test_age_within_and_beyond_the_limit() -> None:
    now = GENERATED + timedelta(days=9, hours=4)
    check = baseline_age_check(stamped(), 7 * DAY, now)
    assert (check.check, check.column, check.limit, check.value, check.passed) == (
        CHECK_BASELINE_AGE,
        None,
        7 * DAY,
        9 * DAY + 4 * 3600,
        False,
    )
    assert check.generated_at == STAMP
    assert check.describe() == (
        "the baseline is 9 days 4 hours old (generated 2026-10-07T00:00:00Z; limit 7 days)"
    )
    assert baseline_age_check(stamped(), 10 * DAY, now).passed


def test_an_age_equal_to_the_limit_passes() -> None:
    limit = 3 * DAY
    assert baseline_age_check(stamped(), limit, GENERATED + timedelta(seconds=limit)).passed
    one_more = GENERATED + timedelta(seconds=limit + 1)
    assert not baseline_age_check(stamped(), limit, one_more).passed
    # Fractions of a second are dropped, never rounded up into a failure.
    almost = GENERATED + timedelta(seconds=limit, microseconds=999_999)
    check = baseline_age_check(stamped(), limit, almost)
    assert (check.value, check.passed) == (limit, True)


def test_a_baseline_without_a_stamp_fails_and_says_why() -> None:
    check = baseline_age_check(stamped(None), DAY, GENERATED)
    assert (check.passed, check.value, check.generated_at) == (False, 0, None)
    assert check.describe() == (
        "the baseline has no 'generated_at' time (write it with --record-time)"
    )


@pytest.mark.parametrize("stamp", ["2026-10-07", "yesterday", "1791331200"])
def test_a_malformed_stamp_fails_and_says_why(stamp: str) -> None:
    check = baseline_age_check(stamped(stamp), DAY, GENERATED)
    assert (check.passed, check.value, check.generated_at) == (False, 0, stamp)
    assert check.describe() == (
        "the baseline's 'generated_at' is not a UTC time like 2026-10-16T04:06:00Z: " + repr(stamp)
    )


def test_clock_skew() -> None:
    # Up to the tolerance ahead of the clock: 0 seconds old.
    now = GENERATED - timedelta(seconds=CLOCK_SKEW_TOLERANCE)
    check = baseline_age_check(stamped(), DAY, now)
    assert (check.passed, check.value) == (True, 0)
    assert check.describe().startswith("the baseline is 0 seconds old")
    # Later than that: an error, not an age.
    later = GENERATED - timedelta(hours=2)
    check = baseline_age_check(stamped(), DAY, later)
    assert (check.passed, check.value) == (False, 0)
    assert check.describe() == (
        "the baseline was generated in the future: 2026-10-07T00:00:00Z is 2 hours ahead "
        "of the clock (2026-10-06T22:00:00Z)"
    )
    just_over = GENERATED - timedelta(seconds=CLOCK_SKEW_TOLERANCE + 1)
    assert not baseline_age_check(stamped(), DAY, just_over).passed


def test_now_in_another_offset_is_the_same_instant() -> None:
    la_paz = timezone(timedelta(hours=-4))
    now = datetime(2026, 10, 7, 20, 0, tzinfo=la_paz)  # 2026-10-08T00:00:00Z
    assert baseline_age_check(stamped(), DAY, now).value == DAY


@pytest.mark.parametrize(
    ("max_age", "now", "error", "match"),
    [
        (True, GENERATED, TypeError, "max_age must be a whole number of seconds"),
        (1.5, GENERATED, TypeError, "max_age must be a whole number of seconds"),
        (0, GENERATED, ValueError, "max_age must be positive"),
        (-1, GENERATED, ValueError, "max_age must be positive"),
        (DAY, datetime(2026, 10, 7), ValueError, "now must be an aware datetime"),
    ],
)
def test_invalid_arguments(max_age: Any, now: datetime, error: type, match: str) -> None:
    with pytest.raises(error, match=match):
        baseline_age_check(stamped(), max_age, now)


# --- the command line ------------------------------------------------------


def run(
    capsys: pytest.CaptureFixture[str], *args: str, epoch: int | None = EPOCH
) -> tuple[int, str, str]:
    with pytest.MonkeyPatch.context() as patch:
        if epoch is not None:
            patch.setenv("SOURCE_DATE_EPOCH", str(epoch))
        code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_record_time_adds_generated_at_after_source(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    code, out, _ = run(capsys, path, "--format", "json", "--record-time")
    assert code == 0
    report = json.loads(out)
    assert list(report)[:3] == ["source", "generated_at", "rows"]
    assert report["generated_at"] == STAMP


def test_without_record_time_the_report_has_no_time(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(write_csv(DATA))
    _, plain, _ = run(capsys, path, "--format", "json", epoch=None)
    _, with_epoch, _ = run(capsys, path, "--format", "json")
    assert plain == with_epoch  # byte-identical: the clock is not even read
    assert "generated_at" not in json.loads(plain)


def test_record_time_without_the_variable_uses_the_clock(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    before = datetime.now(UTC).replace(microsecond=0)
    _, out, _ = run(capsys, str(write_csv(DATA)), "--format", "json", "--record-time", epoch=None)
    stamp = parse_stamp(json.loads(out)["generated_at"])
    assert stamp is not None and before <= stamp <= datetime.now(UTC)


def test_record_time_writes_the_json_output_file(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "report.json"
    code, out, _ = run(capsys, str(write_csv(DATA)), "--json-output", str(target), "--record-time")
    assert code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["generated_at"] == STAMP
    assert STAMP not in out  # Markdown on stdout has no stamp


def test_record_time_needs_a_json_report(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run(capsys, str(write_csv(DATA)), "--record-time")
    assert excinfo.value.code == 2
    assert "--record-time needs a JSON report (--format json or --json-output)" in (
        capsys.readouterr().err
    )


def test_a_bad_source_date_epoch_is_a_usage_error_only_when_used(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = str(write_csv(DATA))
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "soon")
    assert main([path, "--format", "json"]) == 0  # not read without the options
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main([path, "--format", "json", "--record-time"])
    assert excinfo.value.code == 2
    assert "invalid SOURCE_DATE_EPOCH: 'soon'" in capsys.readouterr().err


def write_stamped_baseline(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> str:
    baseline = tmp_path / "baseline.json"
    path = str(write_csv(DATA, "before.csv"))
    code, _, _ = run(
        capsys, path, "--format", "json", "--json-output", str(baseline), "--record-time"
    )
    assert code == 0
    return str(baseline)


def test_gate_end_to_end(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_stamped_baseline(write_csv, tmp_path, capsys)
    path = str(write_csv(DATA))
    later = EPOCH + 9 * DAY + 4 * 3600
    code, _, err = run(
        capsys, path, "--baseline", baseline, "--max-baseline-age", "7d", epoch=later
    )
    assert code == 8
    assert err == (
        "check failed: the baseline is 9 days 4 hours old "
        "(generated 2026-10-07T00:00:00Z; limit 7 days)\n"
    )
    code, out, err = run(
        capsys, path, "--baseline", baseline, "--max-baseline-age", "2w", epoch=later
    )
    assert (code, err) == (0, "")
    assert "- Baseline generated: 2026-10-07T00:00:00Z\n" in out
    assert (
        "- pass: the baseline is 9 days 4 hours old "
        "(generated 2026-10-07T00:00:00Z; limit 14 days)\n"
    ) in out


def test_gate_json(write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline = write_stamped_baseline(write_csv, tmp_path, capsys)
    args = [str(write_csv(DATA)), "--baseline", baseline, "--format", "json"]
    code, out, _ = run(capsys, *args, "--max-baseline-age", "36h", epoch=EPOCH + DAY)
    assert code == 0
    report = json.loads(out)
    assert "generated_at" not in report  # the gate does not stamp the current run
    assert list(report["baseline"])[:2] == ["source", "generated_at"]
    assert report["baseline"]["generated_at"] == STAMP
    assert report["checks"] == [
        {
            "check": "baseline_age",
            "column": None,
            "limit": 36 * 3600,
            "value": DAY,
            "passed": True,
            "generated_at": STAMP,
        }
    ]


def test_one_clock_for_the_stamp_and_the_age(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = write_stamped_baseline(write_csv, tmp_path, capsys)
    args = [str(write_csv(DATA)), "--baseline", baseline, "--format", "json", "--record-time"]
    _, out, _ = run(capsys, *args, "--max-baseline-age", "1s")
    report = json.loads(out)
    assert report["generated_at"] == STAMP and report["checks"][0]["value"] == 0


def test_unstamped_baseline_fails_the_gate(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.json"
    _, out, _ = run(capsys, str(write_csv(DATA, "before.csv")), "--format", "json")
    baseline.write_text(out, encoding="utf-8")
    code, out, err = run(
        capsys, str(write_csv(DATA)), "--baseline", str(baseline), "--max-baseline-age", "7d"
    )
    assert code == 8
    assert err == (
        "check failed: the baseline has no 'generated_at' time (write it with --record-time)\n"
    )
    assert "Baseline generated" not in out
    # Without the gate, an unstamped baseline is as good as before.
    assert run(capsys, str(write_csv(DATA)), "--baseline", str(baseline))[0] == 0


def test_max_baseline_age_needs_a_baseline(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run(capsys, str(write_csv(DATA)), "--max-baseline-age", "7d")
    assert excinfo.value.code == 2
    assert "--max-baseline-age needs --baseline" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("45s", 45),
        ("90m", 5400),
        ("36h", 129_600),
        ("7d", 604_800),
        ("2w", 1_209_600),
        (" 7d ", 604_800),
    ],
)
def test_durations(
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    text: str,
    seconds: int,
) -> None:
    baseline = write_stamped_baseline(write_csv, tmp_path, capsys)
    args = [str(write_csv(DATA)), "--baseline", baseline, "--format", "json"]
    _, out, _ = run(capsys, *args, "--max-baseline-age", text)
    assert json.loads(out)["checks"][0]["limit"] == seconds


@pytest.mark.parametrize("text", ["7", "0d", "00h", "-1d", "1.5h", "7y", "7 d", "7D", "", "７d"])
def test_invalid_durations_are_usage_errors(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    baseline = write_stamped_baseline(write_csv, tmp_path, capsys)
    with pytest.raises(SystemExit) as excinfo:
        run(capsys, str(write_csv(DATA)), "--baseline", baseline, f"--max-baseline-age={text}")
    assert excinfo.value.code == 2
    assert f"invalid --max-baseline-age value: {text!r}" in capsys.readouterr().err


def test_profile_file_is_unchanged(write_csv: WriteCsv) -> None:
    # The stamp lives in the rendered report, not in Report: profiles stay comparable.
    report = profile_file(write_csv(DATA))
    assert not hasattr(report, "generated_at")
