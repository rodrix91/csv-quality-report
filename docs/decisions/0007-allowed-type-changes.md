# 0007: Allowed type changes in the schema gate

- Status: accepted
- Deciders: rodrix91
- Issues: #127 (follow-up to #91); amended by #134 (allowed added and removed columns)

## Context

`--fail-on-schema-change` (#91) fails a run for every column added or removed since the baseline and for every change of an inferred type. Some type changes are expected in a living export and handled by its consumers: a quantity that was always whole starts carrying decimals when bulk items are counted in kilos (`int -> float`), a count date starts carrying a time (`date -> datetime`). Until now the only choice was to accept failing runs or to drop the gate, which also hides added and removed columns and real breakages such as an amount turning into text.

## Decision

1. **`--allow-type-change [NAME=]FROM:TO`**, repeatable, valid only with `--fail-on-schema-change` (a usage error otherwise: without that gate type changes never fail a run, so the option would do nothing). `FROM:TO` applies to every column; `NAME=FROM:TO` only to `NAME`, split at the last `=` like the other `NAME=` options. `FROM` and `TO` are the inferred types (`int`, `float`, `bool`, `date`, `datetime`, `string`); an unknown type or `FROM` equal to `TO` is a usage error.
2. **Exact, one-way pairs, no implied lattice.** `int:float` tolerates exactly `int -> float`; it does not tolerate `float -> int` or `int -> string`. The tool does not decide what a widening is: `--require-type` treats `int` as satisfying `float`, but a consumer that parses a column as integer still breaks on `3.5`, so the user names each accepted pair.
3. **Tolerated, not hidden.** An allowed change is left out of `value` (the changes that still fail), so the gate passes when it was the only change; the message names what was allowed (`... (allowed: 'Cantidad' int -> float)`), the JSON item carries the rules (`allowed_type_changes`) and the matched changes (`tolerated`), and the `baseline` comparison, Markdown and JSON, still lists every type change. Added and removed columns are never affected.
4. **No change without the option.** The two JSON fields appear only when rules are given, so reports, messages and exit codes of existing pipelines are byte-identical.
5. **A rule that matches nothing is not an error.** It can only make the gate stricter than the user hoped, never more lenient; failing on it would break a pipeline whose export did not change this time. With `--columns`, a `NAME=` rule on a column left out is a usage error, like every per-column gate.
6. **Python API.** `schema_change_check(comparison, allowed_type_changes)` takes `TypeChangeRule(before, after, column=None)` items (validated on creation; anything else is a `TypeError`); repeated rules count once.

## Consequences

- A pipeline can keep `--fail-on-schema-change` on an export that widens over time and still be stopped by a column that turns into text.
- `--allow-type-change int:float` in every column is broad: an identifier column that gains a decimal (`1001.5`) is tolerated too. The per-column form is the narrower choice and is used in the README example.
- Type changes caused by reading options (a missing `--decimal-comma`) look like any other change; the rule cannot tell them apart, as before.
- Added and removed columns could still only fail the run; #134 (below) extends the same design to them.

## Alternatives considered

| Alternative | Benefit | Cost / why not |
|---|---|---|
| A built-in list of widenings (`--allow-widening`) | One flag | Hides which pairs are accepted, and what a widening is depends on the consumer (see decision 2). |
| Reuse the `--require-type` satisfaction rules | Consistent with that gate | Same objection; that rule answers "can this column be used as TYPE", not "will an existing consumer still work". |
| Glob patterns in `NAME` | One rule for many columns | Names in ERP exports contain `*`, `?` and brackets; no other option takes patterns. Repeat the option instead. |
| Drop allowed changes from the comparison | Shorter report | The comparison is the record of what changed; the gate decides what fails. |
| Fail on a rule that matches nothing | Catches typos | Breaks runs where the export did not change; a typo only makes the gate stricter. |

## Amendment (#134): allowed added and removed columns

Expected column changes had no opt-out either: an ERP upgrade that adds a `Unidad` column, or a lot column that moves to another export, failed every run until the baseline was rotated. The same design is extended to them:

1. **`--allow-added-column NAME` and `--allow-removed-column NAME`**, repeatable, valid only with `--fail-on-schema-change` (a usage error otherwise, for the same reason as decision 1), and `needs --baseline` without a baseline. One exact, case-sensitive name per option, taken as written like `--unique` (commas and `=` are part of it); an empty name is a usage error. Two options instead of one with a direction prefix, because an added column and a removed one are different events for a consumer: a new column rarely breaks a reader, a missing one usually does.
2. **One direction each.** An added name does not allow the removal of a column with that name, and the other way round. A rename is accepted by naming both columns; the tool does not check that they hold the same data.
3. **Tolerated, not hidden**, as decision 3: the change is left out of `value`, the message lists what was allowed in the order of the failure message (added, removed, type changes: `(allowed: added 'Unidad'; removed 'Lote'; 'Cantidad' int -> float)`), the `baseline` comparison still lists every added and removed column, and the JSON item carries `allowed_added_columns` / `tolerated_added_columns` and `allowed_removed_columns` / `tolerated_removed_columns`. Separate keys rather than new items in `tolerated`, so the shape of `tolerated` (type changes) stays what 0.17.0 published.
4. **No change without the options**, as decision 4: each pair of keys appears only when its option is given; reports, messages and exit codes of existing pipelines, with or without `--allow-type-change`, are byte-identical.
5. **A name that matches nothing is not an error**, as decision 5. With `--columns`, a name left out is a usage error: a removed column outside the selection is never reported as removed, and an added one cannot be in the report, so the option could never match.
6. **Python API.** `schema_change_check(comparison, allowed_type_changes=(), allowed_added_columns=(), allowed_removed_columns=())`; names must be non-empty strings (`TypeError` for other items or for a single string passed instead of a list, `ValueError` for an empty name); repeated names count once.

| Alternative | Benefit | Cost / why not |
|---|---|---|
| `--allow-rename OLD=NEW` | Records the intent of a rename | Pairing is a claim the tool cannot check (it compares profiles, not values), and names may contain `=`; two names say exactly what is tolerated. |
| One `--allow-column-change NAME` for both directions | One option | A removed column breaks consumers far more often than an added one; tolerating both by accident hides the dangerous case. |
| Glob patterns in `NAME` | One rule for many columns | Same objection as for type changes. |
