# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behavior).

## [Unreleased]

### Added

- Drift gates for `--baseline`, both failing with exit code 8: `--max-row-drop PCT` fails when the row count fell by more than `PCT` % of the baseline's rows (a truncated export), and `--max-missing-increase PCT` fails for each column whose share of missing values rose by more than `PCT` percentage points (a column that empties out), with one limit for every column. Shares are computed exactly from the `missing` and `rows` counts of both reports, never from the rounded `missing_pct`; a baseline column without a `missing` count fails and says so. JSON check items `row_drop` and `missing_increase`; `Comparison` gains `missing_counts` (`MissingCount` items, with a default, so existing code keeps working), and `csv_quality_report.checks` gains `row_drop_check()` and `missing_increase_checks()`. The corpus gains a case with both gates on the invoice exports (#101).

### Changed

- `docs/related.md` now matches the current ops-field-brief behavior: whitespace and tab-only fields count as missing, repeated keys are counted as extra rows, `--top 0` reports no groups, a negative `--top` exits `2`, an unknown delimiter exits `2`, quoted and multiline fields stay intact, a trailing comma does not break the row, a duplicate header uses the last value, `--help` exits `0`, and the suite has thirty-nine tests.

## [0.12.0] - 2026-10-08

### Added

- `--range` checks `datetime` columns. Bounds may be ISO 8601 date-times (`Escaneo=2026-10-01T08:00:2026-10-01T18:00`, also with seconds, `Z` or an offset), split at the colon between the two bounds, for `date` and `datetime` columns; `YYYY-MM-DD` bounds now also apply to `datetime` columns and compare calendar days. Values with an offset are compared as instants; a column with offsets checked against bounds without them (or the reverse, or with date bounds) and a column that mixes both fail and say why, instead of guessing a time zone (ADR 0003). JSON items of these checks have `expected: "datetime"`. `evaluate()` accepts `datetime` bounds and raises `ValueError` for bounds of different kinds, which used to fail with `TypeError` (#94).
- The guide to Spanish exports gains table rows for time ranges and `--columns`, and a tested pipeline example that profiles three columns of a day-first ERP export and checks a period with `--range` on a date-time column. The corpus gains a `--range` case on date-times with different UTC offsets, compared as instants (#96).

### Fixed

- `profile_file()`, `read_table()` and `reader.open_rows()` accept the path as a string or any path-like object, not only `pathlib.Path`; a string used to fail with `AttributeError: 'str' object has no attribute 'open'`, which is not a `CsvQualityError` (#98).

## [0.11.0] - 2026-10-06

### Added

- `--columns NAMES` profiles only the given columns, in that order, for wide exports; rows are still read whole (duplicates compare full rows) and `--require-columns` checks the full header. An unknown name is a usage error that suggests a padded match; a per-column gate on a column left out is a usage error. JSON gains `selected_columns` and `header_columns`, Markdown `Columns: N of M (selected)`; `Report` gains `header` and `selected_columns`, and the API a `columns` argument (#89).
- `--baseline REPORT` compares a run with an earlier JSON report of the same source: added and removed columns, type changes, missing-value changes and the row count, in a `Changes since baseline` Markdown section and a `baseline` JSON object. `--fail-on-schema-change` fails the run (exit code 8) on added, removed or retyped columns. Python API: `compare_reports()` and `Comparison`. The corpus gains the next day's invoice export (#91).

## [0.10.0] - 2026-10-05

### Added

- Guide to reading Spanish and Latin American exports (`docs/guides/spanish-exports.md`): a table of which option fixes which export problem, and six worked examples on corpus files. A test runs every command in the guide and compares the output, and `scripts/update_guide.py` regenerates them; the guide ships in the source distribution (#80).
- `--range NAME=MIN:MAX` quality gate (repeatable, either side optional): fails with exit code 8 when a numeric or date column has values outside the inclusive range, showing the observed min and max; a column of another type fails with the reason. JSON items of this check carry `range` and `observed`; `evaluate()` gains `column_ranges` (#84).
- Release workflow: pushing a `vX.Y.Z` tag, or publishing a release from the web page, checks that the tag matches the package version, builds the sdist and the wheel, runs the test suite from them and attaches both files to the GitHub release, creating it with the CHANGELOG section as notes (`scripts/release_notes.py`) when needed (#86).

## [0.9.0] - 2026-10-05

### Added

- `--number-affix TEXT` (repeatable) reads numbers written with a currency symbol, a unit or a percent sign (`$ 1.234,56`, `Gs. 50.000`, `12,5 kg`, `15 %`). The affix is removed only when a number remains; each column reports how many cells had each affix (`affixes` in JSON, a `Number affixes` Markdown line), which exposes mixed currencies or units. JSON also gains `number_affixes`; the corpus gains an invoice export (#73).
- `--max-affixes NAME=N` quality gate (repeatable): fails with exit code 8 when a column contains more than N distinct number affixes, such as two currencies or two units, and names the affixes with their cell counts; JSON items of this check carry `found`. It requires `--number-affix`; `evaluate()` gains `column_max_affixes` (#75).
- `--accounting-negatives` reads `(1.234,56)` and `1.234,56-` (trailing minus, as SAP writes it) as negative numbers, also with affixes (`($ 5)`, `$ (5)`); values that would not be numbers stay as written. JSON gains `accounting_negatives`, Markdown an `Accounting negatives` line; the corpus gains an ERP trial balance (#77).

## [0.8.0] - 2026-10-05

### Added

- Excel's `sep=` first line (`sep=;`, also quoted or after a BOM) is skipped instead of being read as the header. `--delimiter auto` uses the declared separator; a different explicit delimiter, including the default comma, stops with exit code 7 and names the declared one. Error line numbers still count the skipped line. JSON gains `sep_line`, and the Markdown delimiter line says when it was declared (#66).
- `--date-order` accepts 12-hour times (`10/5/2026 2:30:00 PM`, `2:30pm`, `2:30 p.m.`, the Spanish `2:30 p. m.` with no-break spaces), read as 24-hour ISO 8601; hours outside 1 to 12 with a marker stay text and are named in the type hint (#68).
- The Markdown table gains a `Mean` column after `Max`, with the same value as the JSON `mean` (empty for non-numeric columns), so terminal output and GitHub Action job summaries show it (#70).
- The end-to-end corpus can hold error cases, whose reference is the message printed on stderr (`expected/<name>.txt`); the first one is a `sep=;` file read with the wrong delimiter.

## [0.7.0] - 2026-10-05

### Added

- `--date-order dmy|mdy|ymd` reads dates such as `05/10/2026` (optionally with a time) in the given order, never guessed: the column becomes `date` or `datetime` with an ISO 8601 range, impossible dates are named in the type hint as written, and top values keep the original text. JSON gains `date_order`, Markdown a `Date order` line; the corpus gains a day-first ERP export (#61).
- `--bool-words TRUE,FALSE` (repeatable) reads words such as `sí`/`no` or `verdadero`/`falso` as booleans in any case, never assumed; numeric or date words and contradictory pairs are usage errors. Stray values are named in the type hint as written. JSON gains `bool_words`, Markdown a `Boolean words` line; the corpus gains a Spanish Excel export (#63).

## [0.6.0] - 2026-10-05

### Added

- `--thousands SEP` (`dot`, `comma` or `space`) recognizes numbers such as `1.234,56`, `1,234.56` or `1 234,56`. Only correctly grouped numbers are normalized; top values keep the text as written; conflicts with the decimal mark are usage errors (#54).
- End-to-end corpus in `tests/corpus`: realistic files run with their options and compared byte for byte with hand-checked JSON reports and exit codes; `scripts/update_corpus.py` regenerates them after an intended change. The corpus ships in the source distribution (#56).

### Fixed

- The source distribution now includes `scripts/update_corpus.py`, which the corpus tests load; a new CI job builds the sdist and runs the test suite from it, so a file missing from `MANIFEST.in` fails the build (#58).

## [0.5.0] - 2026-10-05

### Added

- `type_hint` for `string` columns where at least 90% of the cells fit one other type: the type, the conforming share, and the stray values that block it (JSON field and a `Mostly typed` Markdown line). Values are classified once per distinct value with cheap prefilters and C-level counting; no cost on the 1,000,000-row benchmark, about 0.7 s in the worst case of one stray among 1,000,000 distinct integers (#43).
- `--require-type NAME=TYPE` quality gate (repeatable): fails with exit code 8 unless the column can be used as the type (int satisfies float, date satisfies datetime), and names the stray values when a type hint explains the failure; JSON items of this check add `expected` and `actual` (#45).
- `--encoding NAME` reads files in any text encoding (`cp1252`, `latin-1`, `utf-16`...), with stdin, gzip and delimiter detection; the canonical name is reported (`encoding` in JSON, a Markdown line when not UTF-8). The UTF-8 error now points to the option. Encodings are still never guessed (#47).
- `--max-field-size N` raises Python's CSV field size limit (131,072 characters) for files with long text fields; the default is unchanged, the limit is restored after the run, and the field-limit error now names the option (#48).
- `min_length` and `max_length` per column in JSON, in characters over the non-missing stripped values, to spot truncated or malformed codes (#49).

### Changed

- Checking whether a value is an integer no longer converts it unless it is close to Python's digit limit, which makes type inference slightly faster.

## [0.4.0] - 2026-10-05

### Added

- `--json-output FILE` writes the JSON report to a file while stdout keeps the chosen format, in one pass; written even when a gate fails; new exit code 9 when the file cannot be written (#30).
- GitHub Action (`action.yml`): `uses: rodrix91/csv-quality-report@<ref>` profiles a CSV once, writes the Markdown report to the job summary, saves the JSON report and fails the step on a failed gate; outputs `exit-code`, `passed` and `report-json`. Inputs reach the shell only through environment variables. A new CI job runs the action on the examples, expecting one pass and one failed gate (#31).
- `--max-missing-column NAME=PCT` (repeatable) sets a missing-value limit per column, overriding `--max-missing`; a limit for a column that is not in the header fails as a `required_column` check. `evaluate()` gains an optional `column_max_missing` argument (#32).
- Per-column count of cells with leading or trailing whitespace: `untrimmed` in JSON and an `Untrimmed values` line in Markdown when present. Cells are now counted as read and merged by stripped value once per distinct value; speed and memory are unchanged on the 1,000,000-row benchmark, and slightly faster when every cell is padded (#36).
- `mean` for `int` and `float` columns in JSON, computed from the value counts with exact integer sums or `math.fsum`, rounded to 6 significant digits; `null` when not representable (#37).
- Header names with leading or trailing whitespace are reported (`untrimmed_columns` in JSON, a Markdown line when present), and required-column failures suggest the padded name that matches after stripping (#39).

## [0.3.0] - 2026-10-05

### Added

- `--top N` sets how many most frequent values each column lists (default 3, unchanged); JSON gains `top_n` (#20).
- Quality gates for pipelines: `--max-missing PCT` and `--max-duplicates N` make the tool exit with the new code 8 when a threshold is exceeded, while still printing the full report; failed checks go to stderr. JSON gains a `checks` list; Markdown adds a `## Checks` section when thresholds are given (#18).
- `--require-columns NAMES` quality gate: fails with exit code 8 for each expected column missing from the header, and names the columns that are present (#21).
- Documented Python API: `profile_file`, `build_report`, `read_table`, `evaluate`, `render_markdown`, `render_json`, `Report`, `ColumnProfile`, `CheckResult` and `CsvQualityError` are importable from `csv_quality_report` (with `__all__`); module paths keep working. The README example is executed by a test (#22).
- `-` as the path reads standard input, including `--delimiter auto`, which no longer needs to seek (#26).
- Gzip-compressed input is detected from its first bytes and decompressed while streaming, for files and for standard input; JSON gains `compressed` and Markdown a `Compression: gzip` line. On a 1,000,000-row file the 14 MB `.csv.gz` gives the same report as the 55 MB CSV with the same memory use (#27).

### Changed

- `HANDOFF.md` is restored unchanged as a historical record of the 0.1.0 preparation, with a note on top pointing to the current documentation. It had been removed in #15; project history is kept, not deleted.

## [0.2.0] - 2026-10-05

### Added

- `--version` prints the installed version.

- `--delimiter CHAR` for semicolon, tab, pipe or any single-character separator, with the aliases `tab`, `comma`, `semicolon` and `pipe` (#1).
- `--decimal-comma` to infer floats written as `10,5` (#2, #5).
- `--delimiter auto`: deterministic detection among `,` `;` tab and `|` that stops with exit code 7 instead of guessing when the file is ambiguous (#3, #6).
- JSON output: `delimiter` and `delimiter_detected` fields. Markdown output names the delimiter when it is not the default comma.
- `reader.open_rows()` and `profile.profile_file()` for streaming use from Python.
- ADR 0002 documenting the streaming design.
- `min`/`max` for `date` columns, as ISO strings (#11).
- `datetime` type for strict ISO 8601 date-times, with a range that compares offsets as instants and is omitted when offset-aware and local values are mixed (#10).
- `--na TOKENS` to count values such as `NA`, `null` or `s/d` as missing, at no per-row cost; JSON gains `na_tokens` (#9).
- `scripts/update_readme_samples.py` regenerates the README samples from real runs.
- CI measures line and branch coverage (subprocess CLI runs included) and requires 100%; new tests cover malformed CSV (field over the `csv` size limit) and encoding errors with `--delimiter auto`.

### Changed

- Files are profiled in a single streaming pass instead of being loaded into memory: on a 1,000,000-row file, peak memory dropped from 873 MB to 234 MB and time from 6.85 s to 4.92 s, with identical output (#4).
- Errors are reported in the order they occur in the file; with `--max-rows`, the part of the file after the limit is not read.

### Fixed

- The offset of an invalid UTF-8 byte is now counted from the start of the file; with a BOM it used to be three bytes too low.

## [0.1.0] - 2026-10-03

- Initial version: per-column type inference, missing values, distinct counts, min/max and top values, duplicate rows, Markdown and JSON output.

[Unreleased]: https://github.com/rodrix91/csv-quality-report/compare/v0.12.0...HEAD
[0.12.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rodrix91/csv-quality-report/releases/tag/v0.2.0
