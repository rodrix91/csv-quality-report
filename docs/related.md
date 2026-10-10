# Related tools

## ops-field-brief

[ops-field-brief](https://github.com/rodrix91/ops-field-brief) is a small standard-library Python CLI that answers three operational questions about one CSV:

- Are the required fields filled? (empty cells and tokens such as `NA`, `null`, `s/d` count as missing)
- Does the business key repeat?
- Which groups account for the rows?

Use `csv-quality-report` for full profiling (types, locales, ranges, quality gates). Use `ops-field-brief` when the question is operational completeness.

It is not a replacement and is not a production pipeline.
