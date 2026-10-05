# 0001: Architecture of csv-quality-report

- Status: accepted (prototype/alpha)
- Deciders: rodrix91

## Context

Analysts want a one-command data-quality summary of a local CSV. The tool should install anywhere Python 3.11+ exists, with nothing to download at runtime, and be small enough to read in one sitting.

## Decision

- A standard-library-only Python package (`src/` layout) with small single-purpose modules: `reader` → `profile` (using `inference`) → `render`, wired together by `cli`. The data flows one way; `reader` returns a plain `Table`, `profile` returns a plain `Report`, and renderers only format a `Report`.
- Read the whole file into memory with `csv` from the standard library. *(Superseded by [0002](0002-streaming-profile.md): the file is now profiled in a single streaming pass.)*
- Strict UTF-8 (BOM tolerated); anything else is a clear error, not a guess. *(Complemented in 0.5.0: another encoding can be named explicitly with `--encoding`; it is still never guessed.)*
- Errors are exceptions carrying an exit code; only `cli.main` turns them into stderr messages and exit codes.
- Type inference is a small ordered set of regex/`date` checks over all non-missing values of a column.

## Alternatives considered

| Alternative | Benefit | Cost / why not now |
|---|---|---|
| pandas (`describe`, `read_csv`) | Far richer stats, robust parsing, encoding options | Large runtime dependency (and NumPy) for a small tool; slower install; weaker control over the exact error messages and exit codes |
| Streaming single pass with bounded memory | Handles files larger than RAM | Exact distinct counts, top values and duplicate-row detection need unbounded state or approximate sketches; more code and approximations to explain. Deferred |
| Encoding auto-detection (e.g. chardet) | Opens more real-world files | Extra dependency and guessing can silently mis-decode; chosen: fail loudly and tell the user to re-save as UTF-8 |
| Fallback decoding as Latin-1 | Never fails | Silently wrong text for other encodings. Rejected |
| One module / single script | Less structure | Harder to test and extend; the module split costs little |
| Type inference via trial parsing with many formats (dateutil, locales) | Recognizes more dates/numbers | Dependency or large heuristic surface; false positives. Chosen: strict, documented patterns *(Complemented after 0.6.0: local number and date layouts are read only when named, with `--decimal-comma`, `--thousands` and `--date-order`; the patterns stay strict and nothing is guessed.)* |
| Reject duplicate column names with an error | Simple | Real-world files have them; a deterministic `_2`, `_3` suffix keeps the report usable |

## Consequences

- Positive: zero runtime dependencies, deterministic output, easy to test via the CLI.
- Negative: memory use grows with file size; the inference heuristic is limited (see README "Limitations"); non-UTF-8 files must be converted first.
- Revisit if users need large files (streaming/sketches) or more encodings/delimiters.
