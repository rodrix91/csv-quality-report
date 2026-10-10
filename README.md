# csv-quality-report

> **Status: prototype/alpha.** Maintained by [rodrix91](https://github.com/rodrix91). Interfaces and output formats may change without notice.

A small command-line tool that gives a quick data-quality check of a CSV file before you use it.

## Problem and scope

Before loading a CSV into a notebook or pipeline, analysts and engineers usually want a fast answer to: *what types are these columns, how much is missing, are there duplicate rows, and what do the values look like?* `csv-quality-report` answers that for one local file with one command.

Per column it reports:

- inferred type (`int`, `float`, `bool`, `date`, `datetime`, `string`)
- missing count and percentage
- distinct count (non-missing values)
- min / max (numeric and date columns)
- top 3 most frequent values (configurable with `--top`)

At dataset level it reports the row count and the number of duplicate rows.

Out of scope: data cleaning, schema validation, automatic encoding detection (other encodings are read when named with `--encoding`), network sources.

## Requirements

- Python 3.11 or newer
- Runtime dependencies: **none** (standard library only)
- Development: `pytest`, `ruff`, `mypy`, `build` (pinned in `requirements-dev.txt`; full pins with hashes in `requirements-dev.lock`)

## Install

From a clone of this repository:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock   # exact pins with hashes (alternative: -r requirements-dev.txt)
pip install -e .
```

You can also run the tool without installing it: `PYTHONPATH=src python3 -m csv_quality_report FILE`. Installing the package (`pip install -e .`) is only needed for the `csv-quality-report` command or for using it from other environments; the test suite does **not** require it.

## Usage

```text
python -m csv_quality_report PATH [--format markdown|json] [--max-rows N] [--delimiter CHAR] [--decimal-comma] [--thousands SEP] [--date-order dmy|mdy|ymd] [--bool-words TRUE,FALSE] [--number-affix TEXT] [--accounting-negatives] [--columns NAMES] [--baseline REPORT] [--na TOKENS] [--top N] [--encoding NAME] [--max-field-size N] [--json-output FILE]
                             [--max-missing PCT] [--max-missing-column NAME=PCT ...] [--max-duplicates N] [--require-columns NAMES]
                             [--require-type NAME=TYPE ...]
python -m csv_quality_report --version
```

- `PATH` — the CSV file. Use `-` to read standard input. Gzip-compressed input (`.csv.gz`, or a compressed pipe) is detected from its first bytes and decompressed while streaming; no flag is needed.
- `--format` — `markdown` (default) or `json`.
- `--max-rows N` — analyze only the first `N` data rows (`N >= 1`). The output says when it stopped early (`truncated` in JSON).
- `--delimiter CHAR` — field separator (default `,`). Accepts one character, the aliases `tab`, `comma`, `semicolon` and `pipe`, or `auto` (see below). Use `--delimiter ";"` for files exported from spreadsheets with a Spanish, Portuguese or other comma-decimal locale. Decimal commas (`10,5`) are only parsed as numbers with `--decimal-comma`.
- `--delimiter auto` — detect the separator among `,` `;` tab and `|`. A candidate is accepted only if it gives the same number of fields (more than one) on every one of the first 100 lines (within 64 KiB); quoted fields are respected. If exactly one candidate fits, it is used; a file where every candidate gives one field is treated as a one-column file; otherwise the tool stops with exit code 7 instead of guessing. The chosen delimiter is shown in the report.
- **Excel's `sep=` line**: a first line such as `sep=;` (written by Excel and by tools that target it, sometimes in quotes or after a BOM) declares the separator. It is skipped, not taken as the header. With `--delimiter auto` the declared character is used without sampling; an explicit `--delimiter` must match it, and any other delimiter, including the default comma, stops with exit code 7 and names the declared one (`declares the semicolon delimiter in its first line (sep=;) ...; pass --delimiter auto to follow the file`) instead of producing a one-column report. Error line numbers still count the skipped line. JSON reports `sep_line`; Markdown says `Delimiter: semicolon (declared by a sep= line)`.
- `--decimal-comma` — read floats written with a comma as decimal mark (`10,5`, `-0,25`). With the flag, values written with `.` are no longer floats, thousands separators (`1.234,5`) are recognized only with `--thousands`, and `1,234` means 1.234. Top values keep the original text; min/max are reported as numbers.
- `--encoding NAME` — text encoding of the file: any Python text codec, such as `cp1252`, `latin-1` or `utf-16` (default `utf-8`, with an optional BOM). Works with standard input, gzip and `--delimiter auto`. Unknown names and non-text codecs (`base64`) are usage errors; bytes that are invalid in the chosen encoding stop with exit code 4 and their offset. JSON reports the canonical name as `encoding`; Markdown adds an `Encoding:` line when it is not UTF-8.
- `--max-field-size N` — allow fields of up to `N` characters. Python's `csv` module stops at 131,072 by default, which also protects against an unclosed quote swallowing the rest of a file into one field, so the default is kept; a file that hits it stops with exit code 6 and a message that names this option. The limit is restored after the run (it is process-wide in the `csv` module).
- `--json-output FILE` — also write the JSON report (the same content as `--format json`, including `checks`) to `FILE`, while stdout keeps the chosen `--format`. The data is profiled once. The file is written even when a quality gate fails, so CI can keep it as an artifact; reading errors write no file, and a file that cannot be written stops with exit code 9.
- `--top N` — how many most frequent values to list per column (default 3; `0` lists none). JSON reports the setting as `top_n`.
- `--columns NAMES` — profile only these comma-separated columns, in the order given (repeated names count once); useful for wide ERP or BI exports where a pipeline only cares about a few columns (on a 200,000-row file with 40 columns, profiling 3 of them takes about 2.0 s instead of 3.0 s; reading and comparing whole rows is the part that remains). Rows are still read whole, so ragged rows and encoding errors are still found and duplicate rows still compare full rows; `--require-columns` checks the full header. A name that is not in the header is a usage error (exit code 2) that lists the columns and suggests a name that only differs by surrounding whitespace; a per-column gate on a column left out is a usage error too. JSON reports `selected_columns` (`null` by default) and `header_columns`; Markdown says `Columns: 3 of 40 (selected)`.
- `--baseline REPORT` — compare the run with an earlier JSON report of the same source (written with `--format json` or `--json-output`), to see what changed in a scheduled export: columns added and removed, type changes (`Monto float -> string`), missing-value changes per column (`Peso 12.5% -> 44.4%`) and the row count. Markdown adds a `## Changes since baseline` section; JSON a `baseline` object (`null` without the option). Columns are matched by name; with `--columns`, only the selected ones are compared, so use the same reading options as for the baseline. A baseline that cannot be read or is not a report of this tool stops with exit code 3.
- `--thousands SEP` — thousands separator in numbers: `dot` (`1.234,56`, needs `--decimal-comma`), `comma` (`1,234.56`) or `space` (`1 234,56`, also no-break spaces). A separator is removed only from a correctly grouped number (a first group of 1 to 3 digits, then groups of exactly 3), so `1.23` or `12.34.56` are not taken as thousands; such values then show up in the column's `type_hint`. Type, range and mean use the numbers without separators; top values and text lengths keep the text as written. A separator that is also the decimal mark is a usage error. JSON reports `thousands`; Markdown adds a `Thousands separator:` line.
- `--date-order dmy|mdy|ymd` — read non-ISO dates in the given order: day/month/year (`05/10/2026` is 5 October), month/day/year (`10/05/2026`) or year/month/day (`2026/10/05`). Day and month take one or two digits and the year four (two-digit years are not accepted, since the century would be a guess); the separator is `/`, `-` or `.`, the same one twice; an optional time `H:MM` or `HH:MM:SS` may follow after a space or `T`, also on the 12-hour clock with `AM`/`PM` in any case, with or without dots and spaces (`2:30 PM`, `2:30pm`, `2:30 p.m.`, the Spanish `2:30 p. m.` with no-break spaces); a 12-hour time needs an hour from 1 to 12 and is read as 24-hour (`12 AM` is 00). The order is never guessed: `05/10/2026` reads differently in each order, and a column where every day is at most 12 gives no clue. Matching values are read as ISO 8601, so the column becomes `date` or `datetime`, ISO values keep working alongside, and impossible dates (`31/02/2026`) stay text and appear in the `type_hint` as written. Min and max are reported in ISO 8601 (`2026-10-05`); top values and text lengths keep the text as written. JSON reports `date_order`; Markdown adds a `Date order:` line.
- `--bool-words TRUE,FALSE` — also read these words as booleans, in any case (`casefold`), like `true`/`false`, which always count; repeatable: `--bool-words sí,no --bool-words verdadero,falso` (Spanish Excel writes logical values as `VERDADERO`/`FALSO`). Accents are not removed, so `si` and `sí` are different words and can both be given. Words are never assumed (`no` is also ordinary text). A pair with equal words, a word that is true in one pair and false in another, or a word that is already a number or a date (`1,0`, which would turn quantity columns into text; 0/1 columns are `int`) is a usage error. Only whole values match; a stray value shows up in the `type_hint` as written, top values and text lengths keep the text as written, and `--na` tokens are removed first. JSON reports `bool_words` (a list of pairs); Markdown adds a `Boolean words (true/false):` line.
- `--number-affix TEXT` — text allowed before or after numbers, such as a currency symbol, a unit or a percent sign; repeatable: `--number-affix '$' --number-affix 'Gs.' --number-affix kg --number-affix %`. The affix is removed (case-sensitive, with the spaces next to it, also no-break spaces) only when what remains is a number under `--decimal-comma` and `--thousands`, so `$ 1.234,56`, `US$ 15`, `12,5 kg` and `15 %` become numbers while `$ consultar` stays text and shows up in the `type_hint`. A sign may come before a prefix (`-$ 5` is -5). Numbers are not scaled (`15 %` is 15). Each column reports how many cells had each affix: `affixes` in JSON (`{"Gs.": 6, "US$": 2}`, `{}` by default) and a `Number affixes:` Markdown line, so a column that mixes currencies or units (`kg` and `lb`) is visible instead of being silently averaged. An empty affix, one made only of signs and separators, or one that is a number is a usage error. JSON reports the given texts in `number_affixes`.
- `--accounting-negatives` — read the negative forms of accounting and ERP exports: parentheses (`(1.234,56)`, Excel's accounting format) and a trailing minus (`1.234,56-`, as SAP and other ERPs write it) become `-1.234,56`. It combines with the other options: affixes inside the parentheses or before them (`($ 5)`, `$ (5)`), decimal commas and thousands separators. A value is rewritten only when the result is a number; `(-5)`, `(5`, `5--` or `(ver anexo)` stay as written (and appear in the `type_hint` when they block a type). JSON reports `accounting_negatives`; Markdown adds an `Accounting negatives:` line.
- `--na TOKENS` — comma-separated cell values to count as missing, in addition to empty cells, e.g. `--na NA,null,s/d`. Matching is exact and case-sensitive after stripping spaces. A token list that starts with `-` must be attached with `=`: `--na=-,NA`. Missing tokens are excluded from type inference, distinct counts and top values, so a quantity column with `NA` gaps is still reported as `int`. Duplicate-row detection keeps comparing the raw text.

### Pipes and compressed files

The input is streamed, so it can come straight from another command, compressed or not:

```bash
gunzip -c shipments.csv.gz | python -m csv_quality_report - --delimiter auto
python -m csv_quality_report shipments.csv.gz --format json     # decompressed on the fly
curl -s https://example.org/export.csv | python -m csv_quality_report - --max-duplicates 0
```

On standard input the report names the source `<stdin>`. `--delimiter auto` works on pipes too: it reads its sample, completes the current line and keeps reading the same stream, without seeking. Two limits come with pipes: a non-UTF-8 byte cannot be located by re-reading, so the error says the offset is not available; and corrupt or truncated gzip data stops with exit code 3. For gzip files on disk, the offset of an invalid byte is counted in the decompressed data.

### Quality gates for pipelines

By default the tool only reports. With thresholds it also decides: the full report is still printed to stdout, every failed check is printed to stderr as `check failed: ...`, and the exit code is **8** when at least one check fails (0 when all pass). A value equal to its limit passes.

- `--max-missing PCT` — fail if any column has more than `PCT` % missing values (0 to 100). The comparison uses the exact percentage, not the rounded `missing_pct` shown in the table.
- `--max-missing-column NAME=PCT` — a missing-value limit for one column, overriding `--max-missing` for it; repeat the option for several columns, and use it with or without `--max-missing` (for example, `--max-missing 5 --max-missing-column comment=100 --max-missing-column shipment_id=0`). The name is exact and case-sensitive and is split from the value at the last `=`; if a name is given twice, the last limit wins. A limit for a column that is not in the header fails as a `required_column` check instead of being ignored, since it usually means a typo or a renamed column.
- `--max-duplicates N` — fail if the file has more than `N` duplicate rows (`0`: none allowed).
- `--require-type NAME=TYPE` — fail unless column `NAME` has type `TYPE` (`int`, `float`, `bool`, `date`, `datetime` or `string`); repeatable, the last type for a name wins. A column satisfies the type when it can be used as it: `int` columns satisfy `float`, `date` columns satisfy `datetime`, and every column satisfies `string`. A column with no values passes (use `--max-missing-column NAME=0` to require values). When a string column fails and its `type_hint` fits the required type, the message names the stray values: `column 'qty' is string, expected int (3 values do not fit: "N/A", "12a")`. An unknown column fails as `required_column`. JSON items of this check also carry `expected` and `actual`.
- `--max-affixes NAME=N` — fail unless column `NAME` contains at most `N` distinct `--number-affix` texts; repeatable, the last limit for a name wins. `NAME=1` stops a column that mixes currencies or units: `column 'Monto' mixes 2 number affixes: "Gs." in 6 cells, "US$" in 2 cells (limit 1)`. Plain numbers without an affix do not count. JSON items of this check also carry `found` (cells per affix). It needs `--number-affix` (without it no affix could be found and the check would always pass, so that is a usage error). An unknown column fails as `required_column`.
- `--range NAME=MIN:MAX` — fail unless every value of column `NAME` lies within `MIN..MAX`, inclusive; repeatable, the last range for a name wins. Either side may be left out (`Peso=0:`, `Cantidad=:5000`). Bounds are numbers for `int` and `float` columns; `YYYY-MM-DD` dates for `date` and `datetime` columns, which compare calendar days (`Escaneo=2026-10-01:2026-10-31` takes all of 31 October); or ISO 8601 date-times for `date` and `datetime` columns, in the forms type inference accepts (`Escaneo=2026-10-01T08:00:2026-10-01T18:00`, also with a space, seconds, `Z` or an offset; a date counts as midnight). Both bounds must be of the same kind, two date-times must both have a UTC offset or both lack one, and MIN must not be greater than MAX, or it is a usage error; the colon that separates MIN and MAX is the one between two bounds, so the colons inside times need no escaping. The check compares the column's min and max: `column 'Peso' has values outside 0..1000 (min -1, max 800)`. A column of another type fails and says so, naming the stray values when its `type_hint` fits (`column 'qty' is string, a range needs int or float values (1 value does not fit: "12a")`). Times are never placed in a guessed time zone: values with an offset are compared as instants against date-time bounds with an offset, and the check fails and says why when the column has offsets and the bounds do not (date bounds included, since the day of `23:30-05:00` depends on the zone), when the bounds have offsets and the column does not, or when the column mixes both and so has no range (see [ADR 0003](https://github.com/rodrix91/csv-quality-report/blob/main/docs/decisions/0003-datetime-ranges.md)). A column with no values passes. JSON items of this check also carry `range` and `observed` (`null` for an open side). An unknown column fails as `required_column`.
- `--fail-on-schema-change` — with `--baseline`, fail (exit code 8) when columns were added or removed or changed type since the baseline: `3 schema changes since the baseline: added 'Moneda'; removed 'Descuento'; 'Monto' float -> string`. Missing-value and row changes stay informational unless one of the two drift gates below is given (or an absolute `--max-missing*` gate).
- `--max-row-drop PCT` — with `--baseline`, fail when the row count fell by more than `PCT` % of the baseline's rows (0 to 100), for example when a scheduled export arrives truncated: `row count fell 60% since the baseline (10 -> 4 rows; limit 50%)`. More rows than the baseline never fail. File-level `row_drop` check in JSON; `value` is the drop in percent (0 when the count did not fall).
- `--max-missing-increase PCT` — with `--baseline`, fail for each column whose share of missing values rose by more than `PCT` percentage points since the baseline (0 to 100): `column 'Peso' missing values rose 31.94 points since the baseline (12.5% -> 44.44%; limit 20 points)`. Unlike `--max-missing-column`, one limit covers every column, including those that are always partly empty, since only the change counts. Every column present in both reports is compared (only the selected ones with `--columns`); added columns are schema changes, not compared here. The shares are computed exactly from the `missing` and `rows` counts of both reports, never from the rounded `missing_pct`, so a rise just above the limit always fails; a baseline column without a `missing` count fails its check and says so. Per-column `missing_increase` checks in JSON; `value` is the rise in percentage points (0 when it did not rise).

## Related

For operational completeness questions (fill rate of required fields, repeated business keys, and top groups) on one CSV, see the complementary tool [ops-field-brief](https://github.com/rodrix91/ops-field-brief).

## Contributing

See [CONTRIBUTING.md](https://github.com/rodrix91/csv-quality-report/blob/main/CONTRIBUTING.md) in the [source repository](https://github.com/rodrix91/csv-quality-report) (not included in the packages).

## License

MIT. See the [LICENSE](https://github.com/rodrix91/csv-quality-report/blob/main/LICENSE) file (included in the [source repository](https://github.com/rodrix91/csv-quality-report), the sdist and the wheel). Copyright (c) 2026 Rodrigo Pantoja Navajas.
