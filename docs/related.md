# Related tools

## ops-field-brief

[ops-field-brief](https://github.com/rodrix91/ops-field-brief) is a small standard-library Python CLI that answers three operational questions about one CSV:

- Are the required fields filled? Empty cells and tokens such as `NA`, `N/A`, `null`, `none`, `s/d`, `s.d.`, `N/D`, `N.D.`, and `-` count as missing. A field that is only whitespace, or only a tab, also counts as missing.
- Does the business key repeat? Blank keys are not counted as repeats. Three identical keys count as two extra rows. Two different keys, each repeated once, also count as two.
- Which groups account for the rows? A blank group is reported as `(blank)`. Top groups are limited to five. `--top` can lower that limit. `--top 0` reports no groups. A negative `--top` exits `2`.

Use `csv-quality-report` for full profiling (types, locales, ranges, quality gates). Use `ops-field-brief` when the question is operational completeness.

`--delimiter` accepts `comma` (default), `semicolon`, `tab`, or `pipe`. Comma remains the default, so existing commands do not change. Semicolon covers the usual Spanish and Latin American spreadsheet export. An unknown delimiter exits `2`.

`--encoding` defaults to `utf-8`. A UTF-8 BOM, common in Excel exports, is stripped. For a Windows Excel export in Spanish, pass `--encoding cp1252` or `--encoding latin-1`. An unknown encoding exits `2`.

A quoted field that contains a comma stays one field. An escaped quote stays in the field. A multiline quoted field stays one row. A trailing comma does not break the row. A duplicate column name in the header uses the last value, following the standard library CSV reader.

A path of `-` reads the CSV from stdin. `--help` exits `0` and lists the arguments.

An unknown `--key` or `--group` exits `2` and names the column. An empty `--required` list exits `2`. `--max-missing` can allow a share of blanks; a value outside 0 to 1 exits `2`.

Status: 0.1.0. Thirty-nine local unit tests. CI runs the same suite on Python 3.10 through 3.13. It is not a replacement and is not a production pipeline.
