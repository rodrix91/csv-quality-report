# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behavior).

## [Unreleased]

### Added

- `type_hint` for `string` columns where at least 90% of the cells fit one other type: the type, the conforming share, and the stray values that block it (JSON field and a `Mostly typed` Markdown line). Values are classified once per distinct value with cheap prefilters and C-level counting; no cost on the 1,000,000-row benchmark, about 0.7 s in the worst case of one stray among 1,000,000 distinct integers (#43).
- `--require-type NAME=TYPE` quality gate (repeatable): fails with exit code 8 unless the column can be used as the type (int satisfies float, date satisfies datetime), and names the stray values when a type hint explains the failure; JSON items of this check add `expected` and `actual` (#45).
- `--encoding NAME` reads files in any text encoding (`cp1252`, `latin-1`, `utf-16`...), with stdin, gzip and delimiter detection; the canonical name is reported (`encoding` in JSON, a Markdown line when not UTF-8). The UTF-8 error now points to the option. Encodings are still never guessed (#47).

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

[Unreleased]: https://github.com/rodrix91/csv-quality-report/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rodrix91/csv-quality-report/releases/tag/v0.2.0
