# Related tools

## ops-field-brief

[ops-field-brief](https://github.com/rodrix91/ops-field-brief) is a small standard-library Python CLI that answers three operational questions about one CSV:

- Are the required fields filled? (empty cells and tokens such as `NA`, `N/A`, `null`, `none`, `s/d`, and `-` count as missing)
- Does the business key repeat? Blank keys are not counted as repeats.
- Which groups account for the rows? A blank group is reported as `(blank)`.

Use `csv-quality-report` for full profiling (types, locales, ranges, quality gates). Use `ops-field-brief` when the question is operational completeness.

`--delimiter` accepts `comma` (default), `semicolon`, `tab`, or `pipe`. Comma remains the default, so existing commands do not change. Semicolon covers the usual Spanish and Latin American spreadsheet export.

`--encoding` defaults to `utf-8`. A UTF-8 BOM, common in Excel exports, is stripped. For a Windows Excel export in Spanish, pass `--encoding cp1252` or `--encoding latin-1`.

An unknown `--key` or `--group` exits `2` and names the column.

It is not a replacement and is not a production pipeline.
