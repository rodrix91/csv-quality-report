# End-to-end corpus

Small files that reproduce real-world CSV problems, each run through the command line with the options in `cases.json`. `tests/test_corpus.py` compares the JSON report of every case with `expected/<name>.json`, byte for byte, together with the exit code.

| File | What it exercises |
|---|---|
| `es_excel_cp1252.csv` | Spanish spreadsheet export: cp1252 with CRLF line ends, `;` separators, amounts like `1.234,56` and `12.345.678,9`, `s/d` gaps (one of them padded, `" s/d "`, which must count as missing and not as untrimmed), values with surrounding spaces, one exact duplicate row. Used twice: plain, and through every kind of quality gate. |
| `utf8_bom_events.csv` | UTF-8 with a byte order mark, ISO 8601 date-times with different offsets (the range compares instants), booleans in two cases, a header name with surrounding spaces. |
| `tab_quoted.tsv` | Tab separated, with quoted fields that contain a newline, a comma and a tab, and an exact duplicate record. |
| `ports_pipe.csv.gz` | Pipe separated and gzip-compressed; both are detected from the content. |
| `erp_day_first.csv` | ERP export with day-first dates (`5/1/2026`, `02/01/2026 8:15`) read with `--date-order dmy`, ISO values in the same columns, grouped weights, and an impossible due date (`30/02/2026`) that keeps the column as text, is named in the type hint and fails `--require-type`. |
| `excel_es_booleans.csv` | Spanish Excel "CSV UTF-8" export: BOM, CRLF, `;`, `VERDADERO`/`FALSO` and `Sí`/`No` flags in several cases read with `--bool-words`, day-first dates and grouped amounts; one `Pendiente` keeps a flag column as text, is named in the type hint and fails `--require-type`. |
| `excel_sep_hint.csv` | Excel export in cp1252 that starts with a `sep=;` line: with `--delimiter auto` the line is skipped and the declared semicolon is used; with the default comma the tool stops with exit code 7 and names the declared delimiter (the second case stores that error message). |
| `mostly_typed.csv` | Stray values (`N/A`, `12a`, `pendiente`) that keep numeric and date columns as text; the type hints name them and `--require-type` fails. |

Cases that end with an error (an exit code other than 0, or 8 for failed quality gates, which still print the report) store the message printed on stderr in `expected/<name>.txt` instead of a JSON report.

When a change to the tool is meant to alter a report, run `python scripts/update_corpus.py` and review the diff of `expected/` before committing: the diff is the change in behavior. `--check` only reports stale files.

The expected reports were checked by hand when the corpus was created (ranges, means, duplicate counts, type hints and failing checks), so they are a reference, not just a snapshot.
