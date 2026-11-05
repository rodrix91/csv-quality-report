"""The time stamped into a report (``--record-time``) and the clock of ``--max-baseline-age``.

Reports carry no time by default, so the same input gives the same bytes on
every run (ADR 0005; the corpus, the guide and report diffs rely on it).
``--record-time`` adds the UTC time the run started, in whole seconds
(``2026-10-16T04:06:00Z``), and a later run reads it back from its
``--baseline`` to know how old that report is (ADR 0008).

``SOURCE_DATE_EPOCH`` (https://reproducible-builds.org/specs/source-date-epoch/),
when set, replaces the system clock for both, so a stamped report and an age
check can be reproduced exactly in tests, golden files and rebuilt pipelines.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime

SOURCE_DATE_EPOCH = "SOURCE_DATE_EPOCH"
# A datetime through year 9999 needs at most 12 epoch digits. Allow many
# leading zeroes for compatibility, but reject pathological inputs before
# regex matching, integer conversion, or embedding them in diagnostics.
_MAX_EPOCH_CHARS = 64
_EPOCH = re.compile(r"[0-9]+")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def current_time(environ: Mapping[str, str] | None = None) -> datetime:
    """The current UTC time in whole seconds, or ``SOURCE_DATE_EPOCH`` when it is set.

    ``environ`` defaults to ``os.environ``. An empty ``SOURCE_DATE_EPOCH`` counts
    as unset; any other value must be a whole number of seconds since
    1970-01-01 UTC, otherwise ``ValueError``.
    """
    text = (os.environ if environ is None else environ).get(SOURCE_DATE_EPOCH, "")
    if text == "":
        return datetime.now(UTC).replace(microsecond=0)
    if len(text) > _MAX_EPOCH_CHARS:
        raise ValueError(
            f"invalid {SOURCE_DATE_EPOCH}: value exceeds {_MAX_EPOCH_CHARS} characters (too long)"
        )
    if _EPOCH.fullmatch(text) is None:
        raise ValueError(
            f"invalid {SOURCE_DATE_EPOCH}: {text!r} (a whole number of seconds since "
            "1970-01-01 UTC)"
        )
    try:
        return datetime.fromtimestamp(int(text), UTC)
    except (OverflowError, OSError, ValueError):
        raise ValueError(f"invalid {SOURCE_DATE_EPOCH}: {text!r} (out of range)") from None


def format_stamp(moment: datetime) -> str:
    """``moment`` (an aware datetime) in UTC as ``YYYY-MM-DDTHH:MM:SSZ``."""
    # datetime.astimezone() silently interprets a naive datetime in the
    # machine's local timezone. A report stamp must describe the same
    # instant on every build runner and machine.
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("moment must be an aware datetime (with a UTC offset)")
    utc = moment.astimezone(UTC)
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
        f"T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}Z"
    )


def parse_stamp(text: str) -> datetime | None:
    """The aware UTC datetime of a stamp written by ``format_stamp``, or ``None``.

    Only that exact form is accepted (no offsets, fractions or lowercase
    ``z``): the stamp is written by this tool, so anything else means the
    report was edited or written by something else.
    """
    if _STAMP.fullmatch(text) is None:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
