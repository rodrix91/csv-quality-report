# 0009: Column freshness (`--max-age`) without a guessed time zone

- Status: accepted
- Deciders: rodrix91
- Issues: #143 (builds on ADR 0003 and ADR 0008)

## Context

A scheduled export can pass every structural gate and still be useless. The ERP job that writes it may have stopped, or a copy step may have picked up last week's file: the columns, types and row count are the same, so the schema, drift and `--range` gates pass. `--max-baseline-age` (ADR 0008) catches a baseline report that stopped moving, but it says nothing about the data itself.

What the job needs to know is how old the newest dispatch, count or invoice date is, compared with when the job runs. Comparing a time in the file with the clock raises two questions that the tool has avoided answering by guesswork elsewhere:

- **Which time zone.** Most exports write local times without an offset (`14/02/2026 15:55`). ADR 0003 decided that `--range` never places such times in a guessed zone. Treating them as UTC, or as the zone of the machine running the job (often a CI runner set to UTC), would be wrong by the export's offset, four hours for La Paz, in a direction that depends on the zone.
- **When a day ends.** A `date` value covers a whole day. Measured from its midnight, a count dated yesterday is a day and a half old at noon today, and a "less than a day old" limit could never pass for data that is up to date.

## Decision

1. **`--max-age NAME=DURATION`**, repeatable, the last limit for a name winning, like the other per-column gates. `DURATION` has the `--max-baseline-age` syntax (a positive whole number with `s`, `m`, `h`, `d` or `w`). The age is the clock minus the column's newest value, in whole seconds (fractions dropped), and an age equal to the limit passes. The clock is the one of ADR 0008: the time of the run, or `SOURCE_DATE_EPOCH` when set, read once per run for `--record-time`, `--max-baseline-age` and every `--max-age` check.
2. **The offset is given, never guessed.** Values with a UTC offset are compared as instants. Values without one are placed at `--utc-offset OFFSET`, a fixed offset (`Z`, `+HH:MM` or `-HH:MM`, up to 14 hours) that applies to every naive value of every `--max-age` column. Without it, a naive column fails and says how to fix it (`give the offset the export writes its times in, such as --utc-offset=-04:00`), the same failure-with-explanation as `--range` uses when a comparison would need a guessed zone. `--utc-offset` without `--max-age` is a usage error, because it would do nothing.
3. **A day lasts until its end.** In a `date` column, the newest day counts until the next midnight at the offset, so `2026-10-17` at `-04:00` is fresh until `2026-10-18T04:00:00Z`. In a `datetime` column, a value without a time is midnight, as in `--range`.
4. **Ahead of the clock is fresh.** A newest value after the clock passes. The check's `value` is negative and the message says how far ahead it is. Planning columns hold future dates on purpose, and an impossible one is what `--range` is for. This is unlike a baseline stamped in the future (ADR 0008), which can only come from a wrong clock or an edited report.
5. **No newest value, no fresh data.** A column with no values fails (`has no values, so it has no newest value to check`). `--range` passes an empty column because no value is out of range, but an empty column is exactly the stale export this gate is for. A column of another type fails and names the stray values when its type hint fits. A `datetime` column that mixes values with and without an offset has no single newest value and fails as well.
6. **Output.** Per-column `max_age` check, `limit` and `value` in seconds, with `newest` (the column's max as the report shows it, or `null`) only on this check, so reports without the option are byte-identical. The message spells out the age: `column 'Despacho' is stale: its newest value 2026-02-14 15:55 is 3 days 4 hours old (limit 2 days)`.
7. **Python API.** `evaluate()` gains `column_max_ages` (seconds per column), `now` (an aware datetime, required with it) and `utc_offset` (a `timedelta` or `None`). Unknown names fail as `required_column`, like the other per-column gates.

## Consequences

- A daily job can fail when its export stopped moving, with the age in the message, and the corpus and the tests reproduce it exactly on a fixed clock.
- Naive exports need one more option. This is deliberate: the alternative is a check that is wrong by the export's offset without saying so.
- A fixed offset is off by one hour for part of the year in zones with daylight saving time. Limits are usually days, so this is documented rather than solved: named zones would need the `tzdata` package on Windows, and the project has no runtime dependencies.
- A negative offset must be written with `=` (`--utc-offset=-04:00`), because `argparse` reads a separate `-04:00` as an option. The help text, the message and the README say so.

## Alternatives considered

| Alternative | Benefit | Cost / why not |
|---|---|---|
| Treat naive times as UTC | No extra option | Wrong by the export's offset, silently, in every zone but UTC. |
| Use the machine's local zone | Right on a desktop in the export's zone | CI runners are usually UTC, so the same job gives different answers in different places. |
| Named zones (`--time-zone America/La_Paz`) | Handles daylight saving time | Needs `tzdata` on Windows, a runtime dependency. A fixed offset covers the common case and can be extended later. |
| Measure a date from its midnight | Simpler | A date that is up to date looks a day old, so short limits cannot pass. |
| Fail when the newest value is in the future | Catches typos like 2062 | Breaks columns that legitimately hold planned dates. `--range` already catches impossible values. |
| An empty column passes, as in `--range` | Consistent with `--range` | An empty column is the stale export this gate is for. |
