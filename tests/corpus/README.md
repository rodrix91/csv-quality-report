# End-to-end corpus

Small files that reproduce real-world CSV problems, each run through the command line with the options in `cases.json`. `tests/test_corpus.py` compares the JSON report of every case with `expected/<name>.json`, byte for byte, together with the exit code.

| File | What it exercises |
|---|---|
| `es_excel_cp1252.csv` | Spanish spreadsheet export: cp1252 with CRLF line ends, `;` separators, amounts like `1.234,56` and `12.345.678,9`, `s/d` gaps (one of them padded, `" s/d "`, which must count as missing and not as untrimmed), values with surrounding spaces, one exact duplicate row. Used twice: plain, and through every kind of quality gate. |
| `utf8_bom_events.csv` | UTF-8 with a byte order mark, ISO 8601 date-times with different offsets (the range compares instants), booleans in two cases, a header name with surrounding spaces. |
| `tab_quoted.tsv` | Tab separated, with quoted fields that contain a newline, a comma and a tab, and an exact duplicate record. |
| `ports_pipe.csv.gz` | Pipe separated and gzip-compressed; both are detected from the content. |
| `mostly_typed.csv` | Stray values (`N/A`, `12a`, `pendiente`) that keep numeric and date columns as text; the type hints name them and `--require-type` fails. |

When a change to the tool is meant to alter a report, run `python scripts/update_corpus.py` and review the diff of `expected/` before committing: the diff is the change in behavior. `--check` only reports stale files.

The expected reports were checked by hand when the corpus was created (ranges, means, duplicate counts, type hints and failing checks), so they are a reference, not just a snapshot.
