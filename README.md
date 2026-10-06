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
python -m csv_quality_report PATH [--format markdown|json] [--max-rows N] [--delimiter CHAR] [--decimal-comma] [--thousands SEP] [--date-order dmy|mdy|ymd] [--bool-words TRUE,FALSE] [--number-affix TEXT] [--accounting-negatives] [--na TOKENS] [--top N] [--encoding NAME] [--max-field-size N] [--json-output FILE]
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
- `--require-columns NAMES` — fail for each comma-separated column that is not in the header, for example when the exporting system renamed or dropped a field. Matching is exact and case-sensitive against the header as reported (after `_2`, `_3` suffixes for repeated names); the message lists the columns that are present. In JSON each required column is a `required_column` check with `value` 1 (present) or 0 (missing).

JSON output always has a `checks` list (empty without thresholds); each item has `check`, `column` (`null` for file-level checks), `limit`, `value` and `passed`. Markdown adds a `## Checks` section only when thresholds are given.

Example: stop a nightly import when an extract has gaps or repeated rows (the step fails on exit code 8):

```yaml
- name: Check the shipments extract before loading it
  run: python -m csv_quality_report data/shipments.csv --delimiter auto --na NA,s/d --max-missing 5 --max-duplicates 0 --require-columns shipment_id,date,weight_kg --require-type weight_kg=float
```

### Example: Markdown (default)

`examples/sample.csv` contains 8 data rows, one exact duplicate row and several empty cells. Command (run from the repository root):

```bash
python -m csv_quality_report examples/sample.csv
```

Output (captured from a real run, exit code 0):

```markdown
# CSV quality report: examples/sample.csv

- Rows analyzed: 8
- Columns: 8
- Duplicate rows: 1

| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean | Top 3 values |
|---|---|---|---|---|---|---|---|---|
| id | int | 0 | 0.0 | 7 | 1 | 7 | 4.125 | 5 (2), 1 (1), 2 (1) |
| name | string | 0 | 0.0 | 7 |  |  |  | Elena (2), Alice (1), Bob (1) |
| signup_date | date | 1 | 12.5 | 6 | 2024-01-15 | 2024-04-18 |  | 2024-03-11 (2), 2024-01-15 (1), 2024-02-03 (1) |
| age | int | 2 | 25.0 | 5 | 29 | 52 | 38.6667 | 38 (2), 34 (1), 29 (1) |
| score | float | 1 | 12.5 | 6 | 69.5 | 95.75 | 83.2857 | 81.0 (2), 88.5 (1), 92.0 (1) |
| active | bool | 1 | 12.5 | 2 |  |  |  | true (4), false (3) |
| city | string | 1 | 12.5 | 3 |  |  |  | La Paz (4), Santa Cruz (2), Cochabamba (1) |
| last_seen | datetime | 1 | 12.5 | 6 | 2024-04-28T12:00 | 2024-05-04T08:45 |  | 2024-05-03T21:30 (2), 2024-05-02T09:15 (1), 2024-05-03 18:40 (1) |
```

### Example: JSON

```bash
python -m csv_quality_report examples/tiny.csv --format json
```

Output (captured from a real run, exit code 0):

```json
{
  "source": "examples/tiny.csv",
  "rows": 3,
  "truncated": false,
  "delimiter": ",",
  "delimiter_detected": false,
  "sep_line": false,
  "na_tokens": [],
  "top_n": 3,
  "compressed": false,
  "encoding": "utf-8",
  "thousands": null,
  "date_order": null,
  "bool_words": [],
  "number_affixes": [],
  "accounting_negatives": false,
  "duplicate_rows": 0,
  "untrimmed_columns": [],
  "columns": [
    {
      "name": "item",
      "type": "string",
      "type_hint": null,
      "missing": 0,
      "missing_pct": 0.0,
      "distinct": 2,
      "min": null,
      "max": null,
      "mean": null,
      "min_length": 4,
      "max_length": 5,
      "top_values": [
        {
          "value": "apple",
          "count": 2
        },
        {
          "value": "pear",
          "count": 1
        }
      ],
      "untrimmed": 0,
      "affixes": {}
    },
    {
      "name": "qty",
      "type": "int",
      "type_hint": null,
      "missing": 1,
      "missing_pct": 33.3,
      "distinct": 2,
      "min": 3,
      "max": 5,
      "mean": 4.0,
      "min_length": 1,
      "max_length": 1,
      "top_values": [
        {
          "value": "3",
          "count": 1
        },
        {
          "value": "5",
          "count": 1
        }
      ],
      "untrimmed": 0,
      "affixes": {}
    }
  ],
  "checks": []
}
```

### Behavior details

- **Column names with surrounding whitespace** (`" date"`, common in files exported with `, ` separators) are kept exactly as read, so nothing is renamed behind your back, but they are reported: `untrimmed_columns` in JSON and a `- Column names with surrounding whitespace:` line in Markdown when present. When `--require-columns` or `--max-missing-column` names a column that only matches after stripping, the failure message suggests the real name (`did you mean ' date'?`).
- **Untrimmed values**: cells with leading or trailing whitespace (`"AR "`) are compared after stripping, so they count as the same value as `"AR"`, but they are a data-quality problem of their own (joins and lookups fail on them). Each column reports how many non-missing cells had surrounding whitespace: `untrimmed` in JSON, and a `- Untrimmed values: code (3), city (1)` line in Markdown only when some column has them. Whitespace-only cells are missing, not untrimmed.
- **Missing value** = an empty cell or a cell with only whitespace. Other tokens such as `NA` or `null` are treated as missing only when listed with `--na`; the tokens used are reported (`na_tokens` in JSON, an `Also counted as missing` line in Markdown).
- Values are whitespace-stripped before type inference and counting.
- **Type inference** looks at all non-missing values of a column, in this order: `bool` (`true`/`false`, any case, and the words given with `--bool-words`) → `int` → `float` → `date` (strict `YYYY-MM-DD`) → `datetime` (ISO 8601 date and time: `YYYY-MM-DDTHH:MM`, a space instead of `T`, optional seconds with up to 6 fraction digits, optional `Z` or `±HH:MM` / `±HHMM` / `±HH` offset; plain dates may be mixed in) → `string`. Compact or partial forms (`20261005T1430`, `2026-10-05T14`) and impossible values (hour 24, `2026-02-30`) are not dates. `0`/`1` columns are `int`. A column with no non-missing values is reported as `string`. Numbers that cannot be represented also make the column `string`: integers with more digits than Python's integer-conversion limit (4300 by default) and floats that overflow to infinity such as `1e999`. As a result the JSON output never contains `NaN` or `Infinity` (it is always standard JSON).
- **Compression in the output**: JSON always includes `compressed` (`true` for gzip input). Markdown adds `- Compression: gzip` only for compressed input.
- **Delimiter in the output**: JSON always includes `delimiter` and `delimiter_detected`. Markdown adds a `Delimiter:` line only when the delimiter is not the default comma or was detected.
- **Duplicate rows** = rows that exactly repeat an earlier row (total rows minus unique rows), comparing raw cell text. Rows are compared through a 128-bit BLAKE2b fingerprint instead of being stored, so the count is exact unless two different rows collide on 128 bits (probability below 1e-20 even for billions of rows).
- **Order of errors**: the file is read once from start to end, and the first problem met is reported. With `--max-rows`, the part of the file after the limit is not read at all.
- **Mostly typed columns**: inference stays strict, so one stray value still makes a column `string`. But when at least 90% of a string column's non-missing cells fit one other type, the report says so and shows the values in the way: `type_hint` in JSON (`{"type": "int", "conforming_pct": 99.98, "nonconforming": 2, "examples": ["N/A", "12a"]}`, `null` otherwise) and a `- Mostly typed: qty is int except 2 values ("N/A", "12a")` line in Markdown. `float` covers ints and floats and `datetime` covers dates and date-times; the narrowest type wins a tie; examples are the most frequent stray values; `conforming_pct` is rounded down, so it never shows 100 while strays exist.
- **Text length** (JSON only): `min_length` and `max_length` per column, in characters, over the non-missing values after stripping; `null` for a column with no values. A code column with `min_length` 1 and `max_length` 2 has truncated entries.
- **Mean** (in JSON and, since 0.8.0, in the `Mean` column of the Markdown table; the table had no such column before): for `int` and `float` columns, the mean of the non-missing values, weighted by how often each value occurs and rounded to 6 significant digits; `null` for other types. Integers are summed exactly and floats with `math.fsum`, so long columns do not drift; integers too large for a float give `null`.
- **Min / max**: numbers for `int` and `float` columns; ISO `YYYY-MM-DD` strings for `date` columns (earliest and latest date); for `datetime` columns the original text of the earliest and latest value (with `--date-order`, dates and date-times are reported in their ISO 8601 form), comparing values with an offset as instants (a plain date counts as midnight). A `datetime` column that mixes values with and without an offset has no range, because a local time could be in any zone. Empty for `bool` and `string`. In JSON they are numbers, strings or `null` accordingly.
- **Top values**: ties are listed in order of first appearance.
- **Duplicate column names** are made unique deterministically: later repeats get `_2`, `_3`, … suffixes (`a,a,a` → `a`, `a_2`, `a_3`; if a suffixed name already exists, the counter keeps increasing).
- **Encoding**: files are read as UTF-8 by default. A leading UTF-8 BOM is accepted and removed. Anything else (e.g. Latin-1, UTF-16) fails with exit code 4 rather than guessing. Files in another encoding are read when it is named with `--encoding` (for example `cp1252`, the usual encoding of spreadsheet exports in Spanish and Portuguese locales); the UTF-8 error message points to that option. The encoding is never guessed.
- Fully blank lines are skipped.

### Errors and exit codes

Errors are printed to stderr as `error: ...`; nothing is written to stdout.

| Exit code | Meaning | Example message |
|---|---|---|
| 0 | Success | |
| 2 | Usage error (bad/missing arguments, e.g. `--max-rows 0`) | argparse message |
| 3 | File cannot be read (missing, directory, permissions) | `error: cannot read 'x.csv': No such file or directory` |
| 4 | Not valid UTF-8 (or not valid in the `--encoding` given) | `error: '/tmp/lat.csv' is not valid UTF-8 (invalid byte at offset 8); re-save the file as UTF-8, or name its encoding with --encoding (spreadsheet exports are often cp1252)` |
| 5 | Empty file (no header row) | `error: '/tmp/empty.csv' is empty (no header row)` |
| 6 | Ragged row (cell count differs from header) or malformed CSV | `error: row at line 3 has 2 fields, expected 3 (from the header)` |
| 7 | `--delimiter auto` cannot pick one separator | `error: cannot detect the delimiter: several separators fit every line (comma, semicolon); pass it explicitly with --delimiter` |
| 8 | A quality gate failed (`--max-missing`, `--max-missing-column`, `--max-duplicates`, `--require-columns`, `--require-type`); the report is still printed | `check failed: column 'weight_kg' has 12.5% missing values (limit 5%)` |
| 9 | The `--json-output` file cannot be written | `error: cannot write 'out/report.json': No such file or directory` |

For Spanish and Latin American exports (cp1252, `;`, `1.234,56`, `05/10/2026`, `VERDADERO`, `Gs. 50.000`, `(1.234,56)`), the [guide to reading Spanish and Latin American exports](docs/guides/spanish-exports.md) has a table of which option fixes which problem and worked examples on real-looking files; its commands and outputs are checked by the test suite.

## Use as a GitHub Action

The repository is also a GitHub Action, so any workflow can check its CSV files. It installs the tool from the action's own checkout, profiles the file once, writes the Markdown report to the job summary, saves the JSON report, and fails the step when a quality gate fails.

```yaml
name: Data quality
on: [push, pull_request]

jobs:
  check-extract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check shipments.csv
        id: quality
        uses: rodrix91/csv-quality-report@main  # pin a release tag or commit SHA for reproducible runs
        with:
          path: data/shipments.csv
          args: --delimiter auto --na NA,s/d --max-missing 5 --max-duplicates 0 --require-columns shipment_id,date
      - name: Keep the JSON report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: data-quality-report
          path: ${{ steps.quality.outputs.report-json }}
```

| Input | Default | Meaning |
|---|---|---|
| `path` | (required) | CSV file, relative to the workspace; gzip is detected |
| `args` | `""` | extra command-line options, split on whitespace (no glob expansion) |
| `python-version` | `3.12` | Python used to run the tool (3.11 or newer) |
| `summary` | `true` | write the Markdown report to the job summary |

| Output | Meaning |
|---|---|
| `exit-code` | the tool's exit code (see "Errors and exit codes") |
| `passed` | `true` when the file was read and every check passed |
| `report-json` | path of the JSON report; empty when the file could not be read |

Inputs reach the shell only through environment variables, never interpolated into the script, so a crafted `args` value cannot run commands. The action sets up its own Python with `actions/setup-python`. The repository's CI runs the action on the example files, once expecting success and once expecting a failed gate.

## Use from Python

The same engine is available as a library. These names are the supported API, importable from `csv_quality_report`: `profile_file`, `build_report`, `read_table`, `evaluate`, `render_markdown`, `render_json`, `Report`, `ColumnProfile`, `CheckResult` and `CsvQualityError`. `profile_file` takes the same options as the command line (`max_rows`, `delimiter`, `decimal_comma`, `na_tokens`, `top_n`) and streams the file.

```python
from pathlib import Path

from csv_quality_report import CsvQualityError, evaluate, profile_file, render_json

try:
    report = profile_file(Path("examples/sample.csv"), delimiter="auto", na_tokens=("NA",))
except CsvQualityError as exc:  # unreadable file, bad encoding, ragged rows...
    raise SystemExit(f"cannot profile: {exc.message} (exit code {exc.exit_code})")

print(report.rows, "rows,", report.duplicate_rows, "duplicate")
for column in report.columns:
    print(
        f"{column.name}: {column.type}, {column.missing_pct}% missing, range {column.min}..{column.max}"
    )

checks = evaluate(report, max_missing=20, required_columns=["id", "last_seen"])
failed = [check.describe() for check in checks if not check.passed]
print("checks failed:", failed or "none")

json_text = render_json(report, "examples/sample.csv", checks)  # same JSON as --format json
```

Run from the repository root, it prints:

```text
8 rows, 1 duplicate
id: int, 0.0% missing, range 1..7
name: string, 0.0% missing, range None..None
signup_date: date, 12.5% missing, range 2024-01-15..2024-04-18
age: int, 25.0% missing, range 29..52
score: float, 12.5% missing, range 69.5..95.75
active: bool, 12.5% missing, range None..None
city: string, 12.5% missing, range None..None
last_seen: datetime, 12.5% missing, range 2024-04-28T12:00..2024-05-04T08:45
checks failed: ["column 'age' has 25% missing values (limit 20%)"]
```

A test runs this example and compares its output, so it stays correct.

## Performance

The file is profiled in a single streaming pass (see [ADR 0002](https://github.com/rodrix91/csv-quality-report/blob/main/docs/decisions/0002-streaming-profile.md)). On a synthetic 1,000,000-row, 8-column logistics file (55 MB, one column of unique IDs), JSON output, CPython 3.13:

| Version | Time | Peak memory |
|---|---|---|
| 0.1 (whole file in memory) | 6.85 s | 873 MB |
| current (streaming) | 4.92 s | 234 MB |

Both versions produce identical reports. Numbers depend on the machine and on the data, mostly on how many distinct values each column has.

## Architecture

```mermaid
flowchart TD
    main["__main__"] --> cli
    cli --> reader
    cli --> profile
    cli --> render
    cli --> errors
    cli --> checks
    checks --> profile
    render --> checks
    reader --> errors
    profile --> reader
    profile --> inference
    render --> profile
    render --> reader
```

| Module (`src/csv_quality_report/`) | Responsibility |
|---|---|
| `__main__.py` | `python -m` entry; calls `cli.main` |
| `cli.py` | argument parsing, error → exit code mapping, output |
| `reader.py` | open the file lazily, decode UTF-8, detect the delimiter, yield validated rows, de-duplicate header names |
| `inference.py` | heuristic type inference for one column |
| `profile.py` | single-pass per-column statistics and duplicate-row count |
| `render.py` | Markdown and JSON output |
| `checks.py` | optional quality gates (`--max-missing`, `--max-missing-column`, `--max-duplicates`, `--require-columns`, `--require-type`) evaluated on a finished report |
| `errors.py` | error classes and exit codes |

Design rationale and alternatives: [docs/decisions/0001-architecture.md](https://github.com/rodrix91/csv-quality-report/blob/main/docs/decisions/0001-architecture.md) and, for streaming, [docs/decisions/0002-streaming-profile.md](https://github.com/rodrix91/csv-quality-report/blob/main/docs/decisions/0002-streaming-profile.md) (in the [source repository](https://github.com/rodrix91/csv-quality-report); not included in the packages).

## Testing

```bash
python -m pytest
```

This works after installing only the dev dependencies (`pip install -r requirements-dev.txt`) from the repository root: pytest is configured with `pythonpath = ["src"]`, and the tests that start a subprocess set `PYTHONPATH=src` themselves.

Tests (`tests/`) are behavior tests that call the CLI: happy path, missing values, ragged rows, empty file, bad encoding (Latin-1, UTF-16), BOM, duplicate column names, JSON output, `--max-rows`, `--delimiter` (including detection), `--decimal-comma`, and exit codes. Two tests check that the Markdown and JSON samples in this README match a real run. Another test runs the "Use from Python" example and compares its output. An end-to-end corpus of realistic files (a cp1252 spreadsheet export with `1.234,56` amounts, an ERP export with day-first dates, a Spanish Excel export with `VERDADERO`/`FALSO` and `Sí`/`No` flags, an Excel export that starts with `sep=;`, an invoice export with currency symbols and units, an ERP trial balance with accounting negatives, a UTF-8 file with a BOM and time zones, quoted multi-line tab-separated data, a gzip-compressed pipe-separated file, mostly typed columns) is checked against hand-verified JSON reports. CI requires 100% line and branch coverage (`coverage run -m pytest && coverage combine && coverage report`), including the CLI runs in subprocesses; the few excluded lines carry a `# pragma: no cover` with the reason. See [CONTRIBUTING.md](https://github.com/rodrix91/csv-quality-report/blob/main/CONTRIBUTING.md) (in the [source repository](https://github.com/rodrix91/csv-quality-report); not included in the packages) for lint, type-check and build commands.

## Limitations

- **Memory grows with distinct values, not file size**: the file is streamed, but exact distinct counts and top values keep one counter entry per distinct value, plus a 16-byte fingerprint per unique row. A column of unique IDs therefore still needs memory proportional to the number of rows.
- **Type inference is a heuristic**: it only recognizes the patterns listed above (e.g. thousands separators only with `--thousands`, decimal commas only with `--decimal-comma`, non-ISO dates only with `--date-order`, booleans other than `true`/`false` only with `--bool-words`, numbers with symbols or units only with `--number-affix`, accounting negatives only with `--accounting-negatives`), and one stray value makes the whole column `string` (the `type_hint` then names the dominant type and the stray values, when 90% of the cells fit it).
- UTF-8 unless `--encoding` names another codec; no automatic encoding detection (gzip compression is handled; other compressions such as zip or bz2 are not). Delimiter detection (`--delimiter auto`) only considers `,` `;` tab and `|`, and only the first 100 lines.
- With `--max-rows`, rows after the limit are not read, so problems in them are not detected.
- Min/max for floats use Python `float` parsing.

## Security notes

- Reads one local file path given on the command line, or standard input with `-`; makes no network calls and writes no files except the one named with `--json-output`. Gzip input is decompressed in a stream, with bounded memory.
- Uses only the Python standard library at runtime.
- CSV content is treated as data only (never executed). Markdown output escapes `|` and newlines in cell text but does not sanitize other Markdown, so render untrusted files' reports with care.

## Contributing

See [CONTRIBUTING.md](https://github.com/rodrix91/csv-quality-report/blob/main/CONTRIBUTING.md) in the [source repository](https://github.com/rodrix91/csv-quality-report) (not included in the packages).

## License

MIT. See the [LICENSE](https://github.com/rodrix91/csv-quality-report/blob/main/LICENSE) file (included in the [source repository](https://github.com/rodrix91/csv-quality-report), the sdist and the wheel). Copyright (c) 2026 Rodrigo Pantoja Navajas.
