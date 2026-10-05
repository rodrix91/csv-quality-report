# 0002: Profile files in a single streaming pass

- Status: accepted
- Deciders: rodrix91
- Supersedes: the "read the whole file into memory" point of [0001](0001-architecture.md)
- Issue: #4

## Context

Version 0.1 decoded the whole file into one string, parsed every row into a list and kept all of them until the report was built. On a 1,000,000-row, 8-column file (55 MB) peak memory was about 873 MB, roughly 16 times the file size, so files of a few GB could not be profiled on an ordinary laptop.

Every statistic the tool reports can be computed from much less than the full table:

| Statistic | What it really needs |
|---|---|
| inferred type, min, max | the set of distinct non-missing values of the column |
| distinct count, top 3 values | a frequency count per distinct value |
| missing count | one counter |
| duplicate rows | to recognize a row seen before |

## Decision

1. **Read lazily.** `reader.open_rows()` opens the file as UTF-8 text (BOM tolerated) and yields validated rows one at a time from `csv.reader`. `read_table()` remains as a thin wrapper that collects the rows, for tests and small files.
2. **One pass, per-column frequency counters.** `profile.profile_rows()` keeps a `Counter` per column. Missing cells are counted under the key `""` and moved out at the end, which keeps the inner loop branch-free.
3. **Batch the counting.** Rows are taken in batches of 10,000, transposed into columns with `zip(*batch)`, and counted with `Counter.update`, whose counting loop is implemented in C. Only one batch is held at a time.
4. **Type, min and max from distinct values.** These depend only on which values occur, so computing them over the counter's keys gives exactly the same result as over every cell, and is much cheaper for repetitive columns.
5. **Duplicate rows by fingerprint.** Each row is reduced to a 16-byte BLAKE2b digest of its cell texts, prefixed with the cell lengths so that `["a,b"]` and `["a", "b"]` cannot collide by construction. A false duplicate would need a 128-bit hash collision; the probability stays below 1e-20 even for billions of rows.
6. **Exact invalid-byte offsets without loading the file.** When decoding fails mid-stream, a second pass decodes the raw bytes in 1 MiB chunks with an incremental decoder to report the exact file offset. This also fixes an old off-by-three: with a BOM, the offset used to be counted from after the BOM.

## Results

Same machine, same 1,000,000-row file, JSON output, CPython 3.13:

| Version | Wall time | Peak RSS |
|---|---|---|
| 0.1 (whole file in memory) | 6.85 s | 873 MB |
| this decision | 4.92 s | 234 MB |

The JSON reports of both versions are identical. Tests assert that the streaming path and the in-memory path produce equal reports on random files that cross batch boundaries, with and without `--max-rows`.

## Consequences

- Memory now grows with the number of **distinct values** per column plus 16 bytes (plus set overhead) per **unique row**, not with file size. A column of unique IDs still needs memory proportional to the row count; that is the remaining cost of exact distinct counts.
- Errors are reported in the order they occur in the file. Before, a decoding error anywhere in the file won over a ragged row earlier in it; now the first problem met while reading is reported.
- With `--max-rows`, bytes beyond the limit are no longer decoded, so an invalid byte there is not reported (previously it was).
- Duplicate detection is exact up to a 128-bit hash collision, which is documented.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep rows, only stream the decode | Rows dominate memory; little gain |
| Python `hash(tuple(row))` for duplicates | Noticeably faster than BLAKE2b, but only 64 bits and randomized per process: collisions become plausible around a billion rows |
| Approximate sketches (HyperLogLog, Count-Min) | Bounded memory, but distinct counts and top values would become estimates; the tool's promise is exact numbers. Could be an opt-in mode later |
| Multiprocessing | Larger change for a modest gain at this size; CSV parsing is hard to split safely because of quoted newlines |
