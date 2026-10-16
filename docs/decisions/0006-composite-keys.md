# 0006: Composite keys measured in the profiling pass

- Status: accepted
- Deciders: rodrix91
- Issues: #115 (follow-up to #112)

## Context

`--unique NAME` (0.15.0) costs nothing: every column already counts its distinct stripped values, so the repeated cells are the non-missing cells minus the distinct values. Many ERP and invoicing exports identify a row by two or three columns (invoice and line, branch and document, order and SKU). Each column repeats on its own, so `--unique` fails on all of them, and `--max-duplicates` only sees rows equal in every column. A composite key has no per-column counter to reuse: it needs its own state in the single streaming pass (ADR 0002).

## Decision

1. **`--unique-key NAMES`**, repeatable, one `unique_key` check per distinct key, exit code 8 on a repeat. Names are split at every comma and stripped, exactly like `--require-columns` and `--columns`; a repeated name counts once and the same key given twice gives one check (column order is kept, so `a,b` and `b,a` are two checks with the same result).
2. **One fingerprint per distinct key.** For each checked row the stripped key cells are hashed with the duplicate-row fingerprint (`_row_digest`: BLAKE2b, 128 bits, cell lengths first, so `["x,y", "z"]` and `["x", "y,z"]` differ). Memory grows with the number of distinct keys, not with the length of the values. A false match would need a hash collision.
3. **Missing cells skip the row.** A row with any key cell empty or in `--na` is not checked and is counted as `skipped`, which the message and JSON report. This matches `--unique`, where missing cells never repeat; `--max-missing-column NAME=0` on the key columns requires them.
4. **Exact count, bounded examples.** `value` is the number of checked rows whose key equals an earlier row's key, exact for any file. A fingerprint cannot be read back, so the texts of the first `--top` keys found repeated are kept while scanning, with their exact row counts, and listed most rows first. They are a sample: a key repeated later can be repeated more often.
5. **Keys over unselected columns are allowed.** Rows are read whole, so `--columns` does not limit the key columns (unlike `--unique`, which reads the column's counter and therefore needs it profiled). An unknown name fails as `required_column`, like the other gates.
6. **No cost without the option.** The keys are given to `profile_file()` / `build_report()` (`unique_keys`), measured into `Report.keys` (`KeyProfile`), and checked by `evaluate(unique_keys=...)`, which raises `ValueError` for a key the report did not measure instead of passing silently. The default report, Markdown and JSON are unchanged.

## Consequences

- Measured on this repository's machine (best of three runs, Python 3.12): a 1,000,000-row, 6-column file takes 4.4 s and 156 MB on main and with this change without the option; with a two-column key that has 1,000,000 distinct values, 6.2 s and 249 MB; with a key that repeats 750,000 times, 6.3 s and 244 MB. A 200,000-row, 40-column file: 3.3 s and 95 MB without the option on both, 3.6 s and 115 MB with a two-column key. Hashing is most of the cost; a batch-level fast path counted in C was measured within 5% of the plain loop and was not kept.
- A column whose name contains a comma cannot be part of a composite key. Escaping was rejected to keep one rule for every option that takes a list of names; such a column can still be checked alone with `--unique`, which takes the whole argument as the name.
- Values compare as text: `007` and `7`, `1,0` and `1.0`, `A1` and `a1` are different keys.

## Alternatives considered

| Alternative | Benefit | Cost / why not |
|---|---|---|
| Keep the key texts in a set | Examples for free | Memory grows with the length of the values, unbounded for long text keys. |
| Join the cells with a separator before hashing | Simpler | Ambiguous when a cell contains the separator. |
| Treat a missing cell as a value (`F-1` + empty) | Finds repeated half-keys | A blank line number would collide across unrelated rows; the missing cells are already reported by `--max-missing-column`. |
| Reject keys over columns left out by `--columns` | Same rule as `--unique` | No technical reason: the rows are read whole. |
