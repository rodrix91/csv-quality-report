# 0003: Compare times in `--range` without guessing a time zone

- Status: accepted
- Deciders: rodrix91
- Issue: #94

## Context

`--range NAME=MIN:MAX` (#84) checked numbers and dates, and failed every `datetime` column. Timestamped exports (ERP movements, shipment scans, point-of-sale tickets) need the same gate: no time before the start of the period, none after the extraction.

An ISO 8601 date-time may carry a UTC offset (`2026-10-01T08:00-03:00`, `...Z`) or not (`2026-10-01T08:00`). A value with an offset names an instant. A value without one names a wall-clock time in a zone the file does not state. The profile already follows this: min and max of a `datetime` column compare values with an offset as instants, and a column that mixes both kinds has no min or max (since 0.2.0).

## Decision

1. **Three kinds of bounds**: numbers, dates (`YYYY-MM-DD`) and date-times (the strict ISO 8601 forms type inference accepts). Both bounds of a range are of the same kind, and two date-times both have an offset or both lack one; anything else is a usage error (`ValueError` in the Python API), because such bounds cannot be ordered.
2. **Date-time bounds** apply to `datetime` and `date` columns. A date is midnight, as in min and max. Values and bounds are compared as times; with offsets, as instants, so `2026-10-01T00:00-03:00` equals `2026-10-01T03:00Z`.
3. **Date bounds** apply to `date` columns, as before, and to `datetime` columns without offsets, comparing calendar days: `MAX` 2026-10-31 admits 2026-10-31T23:59. This is what an analyst means by a range of days, and for wall-clock times the calendar day is the one written.
4. **No guessed zone.** The check fails, and says why, when:
   - the column has offsets and the bounds do not, or the reverse;
   - the column has offsets and the bounds are dates (`2026-10-01T23:30-05:00` is 1 October in its own zone and 2 October in UTC);
   - the column mixes values with and without an offset (it has no range).

   Failing is the safe side for a quality gate: a pipeline that passes on a guess can let bad data through, and the message tells the user which bounds to write.
5. **Parsing `MIN:MAX`.** Times contain colons, so the range is split at the colon between two bounds: a regular expression tries a date-time first on each side, then any text without a colon. Each side is then parsed as before, so a mistyped bound still gets its own message. A lone date-time (`t=2026-10-01T08:00`) would split inside its time and is reported as a missing separator.

## Alternatives considered

| Alternative | Benefit | Cost / why not |
|---|---|---|
| Treat values without an offset as UTC (or local time) | Every column can be checked | A guess: the same file gives different results on different machines, or silently wrong ones for exports in local time. |
| A `--timezone` option to place naive values | Explicit, no guess | More surface than the problem needs today; can be added later on top of this decision, since it only turns some failures into comparisons. |
| Date bounds compare midnight (`MAX` 2026-10-31 means 00:00) | One rule for all bounds | Surprising: `2026-10-01:2026-10-31` would reject almost all of 31 October. |
| A different separator for date-times (`MIN..MAX`) | Simple split | Two syntaxes for one option; the colon form stays unambiguous with the split rule above. |

## Consequences

- `--range` now covers every typed column except `bool`.
- The JSON items keep their shape; `expected` gains the value `datetime`, and `range` holds date-times in ISO 8601 (`2026-10-01T08:00:00`).
- Columns with offsets need bounds with offsets; the failure message says so.
