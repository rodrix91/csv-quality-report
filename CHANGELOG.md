# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behavior).

## [Unreleased]

- Advertise Python 3.14 in package metadata following the successful Linux, Windows and macOS CI compatibility matrix; keep runtime requirements, package version, and released tags unchanged.

- Reject ISO datetime hour `24` explicitly before calling `datetime.fromisoformat`, keeping the established strict `00`–`23` contract across Python 3.11–3.14 (Python 3.14 newly accepts `24:00` as next-day midnight). Extend timezone and seconds regression cases; keep range checks and inference consistent across platforms.

- Run the existing Linux, Windows and macOS test matrices under Python 3.14, preserving all earlier version checks and quality gates. Keep package metadata and releases unchanged until the exact-head PR CI succeeds.

- Reject unterminated quoted fields and extra text after a closing quote while profiling CSV files (including gzip, stdin, and legacy CR-only records) instead of silently accepting corrupted cells. Keep valid quoted multiline fields unchanged, report malformed CSV using existing exit code `6`, and preserve previously written JSON reports on parse failure. Add streaming, CLI, source and cross-line-ending regression tests.

- Require matching opening and closing quotes in an optional quoted Excel `sep=` first-line declaration. Malformed half-quoted lines now remain CSV input rather than being silently stripped as delimiter metadata, while valid unquoted or fully quoted declarations, CR/LF/CRLF and case-insensitive `SEP=` remain supported. Add parser and real stream regression checks.

- Fix automatic delimiter detection for long, classic-Mac `CR`-terminated CSV exports: discard a partial record at the 64-KiB sniff window using either `CR` or `LF` line boundaries instead of treating a truncated last record as malformed. Retain `LF`/`CRLF` and single-column behavior, with parser and real CLI regression tests.

- Render invisible CSV-derived Unicode formatting characters as inert `[U+XXXX]` markers in Markdown, including bidirectional controls, soft hyphens, zero-width spaces, word joiners, embedded byte-order marks and Unicode line separators. Preserve JSON values, comparisons, field names and ordinary multilingual text. Add direct helper and CLI regression tests for malicious and benign labels.

- Normalize Python codecs' plain `UnicodeError` (not only `UnicodeDecodeError`) into the existing exit-4 encoding failure in the streaming CSV reader, notably UTF-16 input without a required BOM. Avoid unhandled tracebacks, retain decoder-supplied byte offsets when available, preserve existing JSON artifacts, and cover plain/gzip, early-header and late-iterator failure paths.

- Verify additional JSON report invariants in the reusable GitHub Action before exposing `report-json`: reconcile total header columns with all profiled columns or the ordered `--columns` subset, reject duplicate reported column identities, and require a bounded integer duplicate-row count. Existing real CLI reports, zero-row exports and quality-gate exit codes keep their behavior; add malformed metadata and real selected-column regression coverage.

- Add `--max-row-growth PCT` (with `--baseline`), the counterpart of `--max-row-drop`: fail with exit code 8 when the row count rose by more than `PCT` % of the baseline's rows, for an export job that ran twice into the same file, a join that fans out or a lost date or branch filter, which keep the schema, the types and the missing-value shares and so passed every other gate. `PCT` is a finite percentage of 0 or more without the 0-100 cap (`100` lets the file double); `nan`, `inf` and negative values are usage errors (exit code 2). Exact `Fraction` arithmetic, a growth equal to the limit passes, fewer rows never fail, and a baseline with no rows passes with a message that says the growth cannot be measured. New file-level `row_growth` check in JSON; reports without the option are unchanged. The corpus gains a weekly stock count compared with both row gates, and the Spanish exports guide a line in its table (#216).

- Verify the reusable GitHub Action's fresh JSON artifact before exposing `report-json` or reporting `passed=true`: reject invalid JSON, missing core profile fields and inconsistencies between quality-check results and exit codes 0/8. Preserve the existing freshness safeguard and genuine CLI errors. Add standalone and Action contract regression checks.

- Require the reusable GitHub Action to verify that its JSON report is a **fresh regular file** before advertising `report-json` or `passed=true`. Compare pre-run and post-run file identity, size, modification and change times; reject unchanged, missing or non-file artifacts even if the subprocess reports success. Preserve user-supplied previous reports, existing quality-gate exit code 8 and successful atomic replacements; add direct and end-to-end Action regressions. The standalone CLI and report schema are unchanged.

- Fail closed on multiline or invisible-control GitHub Action `args` and `baseline-args` before Bash `read -a` can silently discard quality gates after the first line. Preserve legitimate tab-separated one-line options and ordinary Unicode text; avoid reflecting malformed `if-baseline-missing` raw values into workflow annotations. Add direct full-C1-range, Action end-to-end and source-package regressions without changing the standalone CLI or the CSV/JSON report formats.

- Reject invisible ASCII C0, DEL and C1 control characters (including ESC, bell and backspace) in GitHub Action CSV, baseline and explicit report paths, before they reach workflow annotations, filesystem access or line-based outputs. Preserve ordinary Unicode path names and the existing workspace/path traversal guarantees. Add parameterized cross-validator and regression tests; standalone CLI handling remains unchanged.

- Escape untrusted ASCII C0 (except horizontal tab), DEL and C1 control characters in CSV-derived Markdown labels, check details and inline code spans to prevent invisible terminal/log manipulation. Preserve existing tab whitespace, CR/LF-as-space behavior inside code spans, original Unicode CSV/JSON content, and existing literal Markdown escapes; add full control-range, metadata/check and real CLI regression coverage.

- Align whole-column `infer_type` with per-cell `value_type` for non-ASCII decimal digits: restrict numeric, ISO temporal and thousands-group parsing to ASCII digits. Unicode numerals (including mixed ASCII/non-ASCII digits) remain original text rather than acquiring contradictory `int`/`float` and `string` classifications; keep existing ASCII, decimal-comma, locale thousands and bool behavior. Add direct and CLI regressions.

- Add `--month-names` (with `--date-order`) for dates whose month is written as a word, as Excel's `dd-mmm-aaaa` format and many ERPs export them: `05-oct-2026`, `05-oct.-2026 14:30`, `5/Octubre/2026`, `30-set-2026` with `dmy`, `Oct-05-2026` with `mdy`, `2026-oct-05` with `ymd`. Spanish and English names and abbreviations are read in any case (also `sept`, and `set`/`setiembre` as written in Peru and Uruguay); a dot may follow an abbreviation, except after a dot separator. Words that are not months leave the value as written, so it shows in the `type_hint`. Reports without the option are unchanged; with it, JSON adds `"month_names": true` and Markdown a `Month names:` line. The Python API gains a `month_names=False` keyword on `profile_rows`, `build_report` and `profile_file`; the corpus gains a Spanish Excel export with month names, and the Spanish exports guide a section on them (#202).

- Add opt-in `--check-baseline-missing-rate` when using `--baseline`: reject a historical `missing_pct` that contradicts its exact integer `missing` count beyond the one-decimal precision of generated reports (±0.05 points). This protects baseline drift analyses against conflicting historical metadata, while preserving default permissive behavior, legacy reports without a valid optional count, rounding boundaries, and unchanged report JSON schemas. The strict check runs before reading the new CSV and returns the existing baseline error code 3. Add API, boundary, legacy and CLI regression tests.

- Reject historical baseline columns with a valid integer `missing` count greater than total baseline rows (including zero-row and huge-count cases). Such impossible counts could distort exact missingness-drift checks. Keep missing counts optional for older JSON reports, accept valid boundary counts, reject corrupt baselines at existing exit 3 before reading the CSV, and preserve unchanged results for valid reports. Add direct comparison, loading and CLI regressions.

- Fail closed on malformed historical `--baseline` report metadata before schema/drift comparisons: reject negative row counts, duplicate column names, and non-finite or out-of-range missing percentages (0–100), including arbitrarily large integer input. The file-read error remains exit 3. Preserve valid reports, exact case-sensitive column matching, optional older `missing` counts, and all existing JSON schemas. Add direct comparison, loading and CLI regressions.

- Harden GitHub-friendly Markdown metadata against HTML/link and inline-code injection from untrusted CSV content and prior baseline JSON: free-text lines now use the same literal escaping as the tables, and NA tokens, currency/number affixes, boolean words and baseline source names use dynamically fenced code spans. Preserve ordinary report text, JSON bytes and all data/quality-gate results; add direct rendering and subprocess CLI regressions.

- Support literal `=` characters in `--pattern` CSV header names using `\=` (e.g. `SLA\=met=OK=[0-9]+`) while retaining unescaped `=` as the name/pattern delimiter and allowing regex patterns themselves to contain `=`. Add CLI regressions for passing, failing and malformed pattern selectors.

- Fix the documented `--pattern` example for header names that contain `=`: the README showed `'SLA\\=met=OK=[0-9]+'`, which in single quotes reaches the tool with two backslashes and checks a column named `SLA\\=met` instead of `SLA=met`; it now shows `'SLA\=met=OK=[0-9]+'`, and a test runs the README example through shell-style parsing (#204). The `--help` text of `--pattern` now says that `NAME` ends at the first `=` not preceded by `\`. The `[Unreleased]` notes also lost a literal `\n\n` that had joined two entries.

- Reject blank positions in composite `--unique-key` selectors, including doubled commas, leading/trailing commas and whitespace-only components. Prevent silently checking an incomplete business key; retain valid whitespace-trimmed selections and existing deduplication semantics. Added CLI regression coverage.

- Reject blank positions in `--columns` selections, including leading/trailing commas and whitespace-only entries, to prevent silently profiling fewer columns than requested. Preserve valid trimmed selections and repeated-name deduplication. Add JSON/CLI regressions for invalid and valid selectors.

- Reject blank comma-separated positions in `--require-columns`, including leading/trailing commas and whitespace-only entries, rather than silently dropping a required-field quality gate. Other CSV column-selection options keep their previous parsing behavior, and CLI regressions cover both invalid and valid selections.

- Escaped CSV-derived Markdown content in quality-check messages (column names, repeated keys, allowed-value and regex mismatch examples) so links, HTML, inline code delimiters and newlines cannot alter rendered reports or Action summaries. Regex patterns remain legible in their intentional code spans; JSON and check results are unchanged. Added direct and CLI regressions.

- Hardened Markdown table rendering for CSV-derived source names, column labels, sample values and textual extrema: pipes and CR/LF cannot alter table structure, and Markdown links or HTML tags are displayed literally. JSON remains unchanged. Added direct and real-CLI regression tests.

- The reusable GitHub Action now rejects informational help/version switches in `args` and `baseline-args` (including accepted abbreviations) before invoking the CLI: these options exit 0 without profiling a CSV and could falsely mark a workflow as passed if a report already existed. Added regression and end-to-end checks; CLI help/version behavior remains unchanged.

- The reusable GitHub Action now confines CSV input and optional baseline reads to `GITHUB_WORKSPACE`, rejecting absolute paths, path traversal, symlink escapes, stdin and line breaks with exit code 2. A missing relative baseline remains compatible with `if-baseline-missing: skip`; extra CLI arguments can no longer override the validated `baseline` or `report-path` Action inputs; the standalone CLI is unchanged. Added regressions and Action end-to-end checks.

- The GitHub Action now refuses explicit `report-path` values that are absolute or resolve outside `GITHUB_WORKSPACE`, while preserving the exact relative path in the `report-json` output on success.

- CI now measures 100% coverage, Ruff, formatting, and strict mypy once on Python 3.12 while retaining full Linux compatibility tests on Python 3.11/3.13 and the existing Windows/macOS matrix, reducing redundant runner work without lowering quality gates.

- The source distribution now retains `CONTRIBUTING.md`, `SECURITY.md`, and `CITATION.cff`; CI verifies those files plus the installed `py.typed` marker, and package metadata links directly to citation guidance.

- README now links the private vulnerability-reporting guidance in `SECURITY.md` from the security notes.

- README now documents how to verify release SHA-256 checksums and GitHub provenance attestations, while noting that historical releases may predate those guarantees.

- Release builds now generate GitHub artifact provenance attestations for the wheel and source distribution, signed through GitHub OIDC/Sigstore and pinned to `actions/attest` v4.2.2 by commit SHA.

- GitHub Actions checkouts now disable persisted Git credentials because CI and release jobs do not push repository changes.

- Release artifacts now include a `SHA256SUMS` file so downloaded wheels and source distributions can be independently verified.

- The release job now has an explicit timeout so a stuck build, install, or release test cannot occupy a runner indefinitely.

- CI jobs now have explicit conservative timeouts so a hung test or platform runner cannot consume GitHub Actions indefinitely.

- The contribution guide now names the current `setuptools==84.2.1` build-backend pin instead of the superseded 84.0.0 value.

- The distribution metadata now links directly to the repository security page alongside documentation, issues, and contribution guidance.

- The package now ships a PEP 561 `py.typed` marker so downstream type checkers can recognize the public Python API as typed. CI verifies the marker survives source-distribution packaging and installation.

- Package metadata now includes project URLs, search keywords, and classifiers so built distributions expose the repository, changelog, issues, contribution guide, documentation, supported Python versions, and project status more clearly.

### Added

- `--skip-lines N`: skips the first `N` lines of the file before the header, for ERP and spreadsheet exports that start with title lines (report name, period, issue time, a blank line), which could not be profiled at all: the first title became a one-field header, so the real header failed as a ragged row (exit code 6), and `--delimiter auto` failed (exit code 7). The lines are skipped as text, before anything is parsed, after decoding (so `--encoding`, gzip and standard input work as usual) and after a `sep=` first line, which is not counted in `N`; `--delimiter auto` samples the lines after them, and error line numbers still count them. A file that ends before a header is found stops with exit code 5 (`has no header row: it ends within the 4 lines skipped by --skip-lines`). JSON reports `skipped_lines` right after `sep_line`, and Markdown `Skipped lines: N (before the header)`, only when `N > 0`, so reports without the option are byte-identical. `open_rows()`, `read_table()` and `profile_file()` gain `skip_lines`; `Table`, `RowStream` and `Report` gain `skipped_lines`. The corpus gains an ERP sales export in cp1252 with three title lines and a blank line, and the guide to Spanish and Latin American exports a section on it (#161).
- Without `--skip-lines`, the two usual symptoms of title lines suggest the count to skip. A one-field header followed by a wider row fails with `...expected 1 (from the header); if this row is the header and the lines before it are titles, skip them with --skip-lines 4`; a failed `--delimiter auto` adds `if the file starts with 3 title lines before the header, skip them with --skip-lines 3` when dropping up to 20 leading lines without separators (`title_lines()` in `csv_quality_report.reader`) lets one separator fit every remaining line. Other errors are unchanged (#161).
- `--skip-footer N`: drops the last `N` records of the file, for ERP and spreadsheet exports that end with a footer after the data (a totals row, a record count, a generated-by line). Without it, a one-field footer failed as a ragged row (exit code 6) or made `--delimiter auto` fail (exit code 7), and a totals row of the header's width was profiled as data: it could turn a date column into `string`, became the maximum of an amount column and failed `--range`, `--unique` or `--pattern`. The footer is counted in CSV records after the header, so blank lines are not counted, and its records are never checked against the header's width. The file is still read once (ADR 0002): each row is held until `N` more were read, so the extra memory is `N` rows, and the 1,000,000-row benchmark keeps its time and peak memory. `--max-rows` still counts data rows. A file with fewer than `N` records after the header stops with exit code 5 (`has 2 records after the header, fewer than the 3 skipped by --skip-footer`). With `--delimiter auto`, when the file fits in the detection sample, its last `N` non-blank lines are left out of it. JSON reports `skipped_footer` right after `sep_line` (after `skipped_lines` when both are present), and Markdown `Skipped footer: N records (after the data)`, only when `N > 0`, so reports without the option are byte-identical. `open_rows()`, `read_table()` and `profile_file()` gain `skip_footer`; `Table`, `RowStream` and `Report` gain `skipped_footer`. The corpus gains an ERP dispatch export in cp1252 with title lines and a footer, used four times, and the guide to Spanish and Latin American exports a section on it (#192).
- Without `--skip-footer`, the two usual symptoms of a footer suggest the count to drop. A ragged row among the last 20 records whose following records are all ragged too fails with `...expected 5 (from the header); if this record and the 1 after it are a footer, skip both with --skip-footer 2 (add one for each totals row above them)`; a failed `--delimiter auto` on a file that fits in the sample adds `if the file ends with 2 footer lines after the data, skip them with --skip-footer 2 ...` when dropping up to 20 trailing lines (`footer_lines()` in `csv_quality_report.reader`) lets one separator fit every remaining line. A title-line suggestion (#161) takes precedence, and neither suggestion is made once its option is given (#192).

### Changed

- GitHub Actions are pinned to the verified commit SHAs behind `actions/checkout@v7` and `actions/setup-python@v7`, with version comments retained for readable Dependabot updates.
- CI cancels superseded runs for the same pull request or branch, avoiding redundant validation after a newer commit is pushed.
- The corpus test that checks error messages name the file relatively now applies to the messages that name a file (delimiter detection and ragged-row errors only give a line), checks that no message holds an absolute path, and still requires at least one error case that names its file.

## [0.22.0] - 2026-10-22

### Added

- `--allowed-values NAME=VALUES` quality gate (repeatable): fails with exit code 8 when a non-missing cell of a column holds a value outside a comma-separated list, for status, currency or unit columns with a closed set of codes: `column 'Estado' has 1 cell outside the allowed values (Entregado, En tránsito, Pendiente): "Devuelto" in 1 cell`. Values compare stripped, case-sensitive and as text; missing cells are not checked. The count is exact and comes from the value counts the pass already keeps, at no extra cost. Per-column `allowed_values` check in JSON with `allowed` and `unexpected`; reports without the option are unchanged. `profile_file()`, `build_report()` and `evaluate()` gain `allowed_values`, and `Report` gains `domains` (`DomainProfile` in `csv_quality_report.profile`). The corpus gains a check of the courier export's statuses (#153).
- `--pattern NAME=REGEX` quality gate (repeatable): fails with exit code 8 when a non-missing cell of a column does not match a regular expression as a whole (`re.fullmatch`), for codes with a fixed format but no fixed list, such as tax ids, postal codes and tracking codes: ``column 'CUIT' has 2 cells that do not match the pattern `\d{2}-\d{8}-\d`: "20300000049" in 1 cell, "30 71000008 0" in 1 cell``. Values are matched stripped and as text, case-sensitive unless the pattern says `(?i)`; missing cells are not checked. The name ends at the first `=`, so the pattern may contain `=`; an empty or invalid pattern is a usage error that quotes the `re` error. The count is exact and comes from the value counts the pass already keeps, each distinct value tested once (about 0.2 s for 1,000,000 distinct values). Per-column `pattern` check in JSON with `pattern` and `mismatched`; reports without the option are unchanged. `profile_file()`, `build_report()` and `evaluate()` gain `patterns`, and `Report` gains `patterns` (`PatternProfile` in `csv_quality_report.profile`). In Markdown the pattern is a code span, so its backslashes and `|` show as written. The corpus gains a customer master export with malformed tax ids and postal codes (#155).

### Changed

- The README's exit-code table and module table name `--allowed-values` and `--pattern` among the gates, and the module table also `--min-rows`.
- The GitHub Action examples in the README pin the latest release tag, `@v0.21.0` (they still named `@v0.19.0`, which lacks the `baseline` inputs of 0.20.0 and `--min-rows` of 0.21.0 that the daily workflow example uses, so that example failed as written). A test now fails when the pin falls more than one release behind the CHANGELOG or the examples pin different tags.
- ADR 0008 records the decision on its open question: `generated_at` stays opt-in (`--record-time`) and will not become the default, so reports stay byte-identical across runs by default.

## [0.21.0] - 2026-10-18

### Added

- `--max-age NAME=DURATION` quality gate (repeatable): fails with exit code 8 when the newest value of a `date` or `datetime` column is more than `DURATION` (`36h`, `2d`, `1w`) before the clock, for exports that are well formed but stale: `column 'Despacho' is stale: its newest value 2026-02-14 15:55 is 3 days 4 hours old (limit 2 days)`. The clock is the one of `--max-baseline-age` (`SOURCE_DATE_EPOCH` replaces it). Times are never placed in a guessed time zone: values with a UTC offset are instants, and values without one need `--utc-offset OFFSET` (`Z`, `+HH:MM` or `-HH:MM`, written `--utc-offset=-04:00` when negative), without which the check fails and says so. A `date` column's newest day counts until its end. A newest value ahead of the clock passes; a column with no values, of another type, or mixing values with and without an offset fails. Per-column `max_age` check in JSON, `limit` and `value` in seconds, with `newest`; reports without the option are unchanged. `--utc-offset` without `--max-age` is a usage error. `evaluate()` gains `column_max_ages`, `now` and `utc_offset`. The corpus gains two freshness cases on a fixed clock (#143, ADR 0009).
- `--min-rows N` quality gate: fails with exit code 8 when the file has fewer than `N` data rows (`the file has 0 data rows (at least 1 required)`), for an export that arrived with only its header, which passed every other gate. It needs no `--baseline`. `N` above `--max-rows` is a usage error. File-level `min_rows` check in JSON; `evaluate()` gains `min_rows`. The corpus gains the header-only export of an ERP job that failed (#148).
- The guide to Spanish and Latin American exports has a section on checking that an export is up to date with `--max-age` and `--utc-offset`, on the day-first ERP export and a fixed clock, verified by the test suite (#145).

### Changed

- The README's module table lists `compare.py`, `clock.py` and every gate in `checks.py`, its design notes link ADRs 0005 to 0009, and it says the ADRs ship in the sdist (they are not in the wheel); it had said they were in neither package.
- The README's exit-code table names every quality gate under code 8 (it listed the first five), and the daily GitHub Action workflow example adds `--min-rows 1`, so an export with only its header never becomes the next baseline.

## [0.20.0] - 2026-10-18

### Added

- GitHub Action inputs for daily comparisons: `report-path` writes the JSON report to a path in the workspace (parent directories are created; an existing file is never removed by the action), `baseline` passes an earlier report as `--baseline` (one argument, so spaces are fine), `baseline-args` holds the options that need the baseline and is added only when it is used, and `if-baseline-missing` (`fail`, the default, or `skip`) decides what a missing baseline file does: `skip` runs without the baseline, with a warning annotation, so the first run of a scheduled pipeline (or a run after the kept report expired) uses the same step. New output `baseline-used`. `baseline-args` without `baseline`, any other `if-baseline-missing` value and a `report-path` with a line break are errors (exit code 2). Without the new inputs the action runs as before. The README has a daily workflow that keeps the report of the last successful run with `actions/cache` and checks its age with `--max-baseline-age`; the CI `action` job runs a baseline chain, and a test checks that every input and output is documented in the README (with its default) and reaches the script only through an environment variable (#138).
- The guide to Spanish and Latin American exports has a section on comparing a weekly export with the previous one: the corpus stock counts compared with a stamped baseline, with `--fail-on-schema-change`, `--allow-type-change` and `--max-baseline-age`, once with a fresh baseline and once with one left two weeks old, plus the shell lines of a job that keeps the report as the next baseline only when every check passed. Its option table gains a row for `--max-baseline-age`. Guide samples may start with environment assignments (`$ SOURCE_DATE_EPOCH=1791806400 python -m csv_quality_report ...`), set only while that sample runs, so outputs that depend on the clock are verified by `tests/test_guide.py` too (#140).

### Changed

- The GitHub Action example in the README pins the latest release tag, `@v0.19.0` (it still named `@v0.17.0` after 0.18.0 was released).

## [0.19.0] - 2026-10-16

### Added

- `--allow-added-column NAME` and `--allow-removed-column NAME` (repeatable, need `--fail-on-schema-change`): an added or removed column with that exact, case-sensitive name is not counted as a schema change, for column changes consumers handle, such as an ERP upgrade that adds a `Unidad` column or a lot column that moves to another export; a rename is accepted by allowing both names. Type changes and other columns still count. The check says what it allowed (`1 schema change since the baseline: removed 'Lote' (allowed: added 'Unidad')`), `value` counts only the changes not allowed, and the JSON `schema_change` item gains `allowed_added_columns` and `tolerated_added_columns`, or `allowed_removed_columns` and `tolerated_removed_columns`, only when the matching option is given, so reports without them are byte-identical. A name left out by `--columns`, an empty name, and the options without `--fail-on-schema-change` are usage errors (exit code 2). `schema_change_check()` gains `allowed_added_columns` and `allowed_removed_columns`. The corpus gains a third weekly stock count (#134, ADR 0007).

## [0.18.0] - 2026-10-16

### Added

- `--record-time`: adds a top-level `"generated_at"` (the UTC time the run started, whole seconds, `2026-10-16T04:06:00Z`) right after `source` in the JSON report, on stdout with `--format json` and in the `--json-output` file. Opt-in: without it reports stay byte-identical. `SOURCE_DATE_EPOCH`, when set, replaces the clock; a value that is not a whole number of seconds is a usage error, and the flag without a JSON report is one too (#129, ADR 0008).
- `--max-baseline-age DURATION` gate (needs `--baseline`): fails with exit code 8 when the baseline report is older than `DURATION`, a positive whole number with `s`, `m`, `h`, `d` or `w` (`36h`, `7d`), so a pipeline that stopped refreshing its baseline is noticed: `the baseline is 9 days 4 hours old (generated 2026-10-07T00:00:00Z; limit 7 days)`. The age comes from the baseline's `generated_at`, never from the file's modification time; a baseline without a stamp, or with one in another form, fails and says why, and a stamp more than 5 minutes ahead of the clock fails as generated in the future. File-level `baseline_age` check with `limit` and `value` in seconds and `generated_at`; the comparison shows `Baseline generated:` in Markdown and `generated_at` in the JSON `baseline` object, only for stamped baselines. `baseline_age_check()` and `format_duration()` in `csv_quality_report.checks`, `Comparison.baseline_generated_at`, `render_json(..., generated_at)` and the `csv_quality_report.clock` module. The corpus gains a stamped weekly stock count and three age checks on a fixed clock; corpus cases may set environment variables (`env`) (#129, ADR 0008).

### Changed

- The GitHub Action example in the README pins the latest release tag, `@v0.17.0`.

## [0.17.0] - 2026-10-16

### Added

- `--allow-type-change [NAME=]FROM:TO` (repeatable, needs `--fail-on-schema-change`): a change of a column's inferred type from `FROM` to `TO` is not counted as a schema change, in every column or only in `NAME`, for widenings consumers handle such as `int:float` (quantities that gain decimals) or `date:datetime` (counts that gain a time). Pairs are exact and one-way; added and removed columns always count. The check says what it allowed (`1 schema change since the baseline: 'Lote' int -> string (allowed: 'Cantidad' int -> float; 'Fecha conteo' date -> datetime)`), `value` counts only the changes not allowed, and the JSON `schema_change` item gains `allowed_type_changes` and `tolerated` only when the option is given, so reports without it are byte-identical. Unknown types, `FROM` equal to `TO` and a `NAME` left out by `--columns` are usage errors. `schema_change_check()` gains `allowed_type_changes` (`TypeChangeRule` in `csv_quality_report.checks`). The corpus gains two weekly stock counts (#127, ADR 0007).

### Changed

- The GitHub Action example in the README pins the latest release tag, `@v0.16.0` (it still named `@v0.14.0` after 0.15.0 was released).

## [0.16.0] - 2026-10-15

### Added

- `--unique-key NAMES` quality gate (repeatable): fails with exit code 8 when two rows share the values of all the comma-separated key columns, such as invoice number and line number, where each column repeats on its own and `--unique` cannot be used. Key cells compare stripped, case-sensitive and as text; a row with a missing key cell (empty or `--na`) is skipped and counted. The message gives the exact number of rows that repeat an earlier key and the first `--top` keys found repeated with their rows; JSON items of the `unique_key` check carry `columns`, `skipped` and `repeated`. The pass keeps one 128-bit fingerprint per distinct key (on 1,000,000 rows with as many distinct keys: about 6.2 s instead of 4.4 s and about 90 MB more); without the option nothing changes. Names are split at every comma like `--require-columns`; unknown names fail as `required_column`; key columns may be left out by `--columns`. `profile_file()` and `build_report()` gain `unique_keys`, `Report` gains `keys` (`KeyProfile`, exported), and `evaluate()` gains `unique_keys`. The corpus gains ERP invoice lines whose numbers restart per branch (#115, ADR 0006).

### Fixed

- A read-only `--json-output` file is refused again, on every platform, with exit code 9 and `cannot write 'FILE': the file is read-only`, and keeps its content. Since the atomic write of 0.14.0 it was silently replaced on Linux and macOS (a rename only needs a writable directory) and failed on Windows with `Access is denied`; the in-place write before 0.14.0 refused it everywhere. Found by a new test on the Windows CI (#122, ADR 0004).

## [0.15.0] - 2026-10-15

### Added

- `--unique NAME` quality gate (repeatable): fails with exit code 8 when a key column (an invoice number, a tracking code) has a non-missing value more than once, which `--max-duplicates` misses when the rows differ elsewhere. Values compare stripped, case-sensitive and as text (`007` and `7` differ); missing cells never repeat. The message gives the exact number of cells that repeat an earlier value and names the most repeated top values; JSON items of the `unique` check carry `repeated`. No extra memory or time: the count is the non-missing cells minus the distinct values each column already tracks. An unknown name fails as `required_column`, a name left out by `--columns` is a usage error, and `evaluate()` gains `unique_columns`. The corpus gains a courier export with a re-sent parcel (#112).

### Changed

- The GitHub Action example in the README pins the latest release tag, `@v0.14.0`, instead of `@main`; the note on pinning a tag or commit SHA is kept.
- The usage synopsis in the README lists every option of `--help` again: the newer quality gates (`--max-affixes`, `--range`, `--unique`) and the `--baseline` gates (`--fail-on-schema-change`, `--max-row-drop`, `--max-missing-increase`, `--max-missing-increase-column`), which it had left out, grouped under `--baseline`, which they need. A test now fails when an option of the parser is missing from the synopsis (#117).
- CI also runs the test suite on Windows and macOS with Python 3.11 and 3.13 (job `platforms`), for the atomic `--json-output` write (`os.replace`), file identity through symbolic and hard links (`os.path.samefile`), paths and line endings. Tests of what Windows lacks are skipped there with the reason: POSIX permission bits, named pipes, and symbolic links without the privilege to create them. `.gitattributes` keeps the test corpus and the examples byte-exact on checkout (#116).

### Fixed

- Windows: stdout and stderr are now always UTF-8 with `\n` line endings. When the output was redirected (`> report.json`, a pipe, a CI log), Python on Windows wrote the report in the ANSI code page, so a JSON report with `guaraníes` was not UTF-8 and differed from `--json-output`, and a name outside the code page (`東京`) crashed with `UnicodeEncodeError`; every line also ended in `\r\n`. The `--json-output` file is written with `\n` too, and the input path is reported as typed (`examples/sample.csv` was `examples\sample.csv` on Windows), in the report's `source` and in error messages, so the same command gives the same bytes on every platform. As a side effect the CLI no longer shortens the path it shows on any platform: `./data.csv` is reported as `./data.csv` instead of `data.csv` (#120, ADR 0005).

## [0.14.0] - 2026-10-15

### Added

- `--max-missing-increase-column NAME=PCT` (repeatable, needs `--baseline`) sets the missing-value drift limit for one column, in percentage points, overriding `--max-missing-increase` for that column; it works with or without the global limit (without it, only the named columns are checked), so a pipeline can let no column lose values except a free-text one. Same `missing_increase` check, message, exact arithmetic and exit code 8; the last limit for a name wins and names are split at the last `=`. A named column that cannot be compared (added since the baseline, removed from the file, or in neither report) fails and says why instead of being ignored; with `--columns`, naming a column left out is a usage error. `missing_increase_checks()` gains a `column_max_increase` mapping and accepts `None` as the global limit. The corpus gains a case with a per-column limit on the invoice exports (#108).

### Changed

- `--json-output` is written atomically: the report goes to a temporary file in the same directory, is synced, and is then moved onto `FILE` with `os.replace`. A failure or an interrupt halfway (a full disk, a killed job) no longer leaves an empty or half-written report or destroys the previous one, which pipelines often reuse as the next `--baseline`; the temporary file is removed and the exit code is still 9. An existing file keeps its permissions, symbolic links are written through, and targets that are not regular files (`/dev/stdout`, a named pipe) are written in place as before. The target's directory must now be writable, and a hard-linked target becomes a new file (ADR 0004). New module `csv_quality_report.output` (#107).

## [0.13.0] - 2026-10-14

### Added

- Drift gates for `--baseline`, both failing with exit code 8: `--max-row-drop PCT` fails when the row count fell by more than `PCT` % of the baseline's rows (a truncated export), and `--max-missing-increase PCT` fails for each column whose share of missing values rose by more than `PCT` percentage points (a column that empties out), with one limit for every column. Shares are computed exactly from the `missing` and `rows` counts of both reports, never from the rounded `missing_pct`; a baseline column without a `missing` count fails and says so. JSON check items `row_drop` and `missing_increase`; `Comparison` gains `missing_counts` (`MissingCount` items, with a default, so existing code keeps working), and `csv_quality_report.checks` gains `row_drop_check()` and `missing_increase_checks()`. The corpus gains a case with both gates on the invoice exports (#101).

### Changed

- `docs/related.md` now matches the current ops-field-brief behavior (whitespace and tab-only fields count as missing, repeated keys are counted as extra rows, `--top 0` reports no groups, a negative `--top` exits `2`, an unknown delimiter exits `2`, quoted and multiline fields stay intact, a trailing comma does not break the row, a duplicate header uses the last value, a UTF-8 BOM on stdin is stripped, `--help` exits `0`, the suite has forty tests, and it links to `CONTRIBUTING.md`) and describes `inventory-policy-lab`.

### Fixed

- `--json-output` no longer overwrites the data it reports on. A target that is the input file or the `--baseline` report, also through another spelling of the path (`dir/../data.csv`), a symbolic link or a hard link, is now a usage error (exit code 2) raised before anything is read; before, the CSV or the baseline was silently replaced by the JSON report. Files are compared by device and inode (`os.path.samefile`); standard input (`-`) protects no file, and a missing input is still the usual read error (exit code 3). Regression tests in `tests/test_output_path_collisions.py` (#104).

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

[Unreleased]: https://github.com/rodrix91/csv-quality-report/compare/v0.22.0...HEAD
[0.22.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/rodrix91/csv-quality-report/compare/v0.12.0...v0.13.0
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
