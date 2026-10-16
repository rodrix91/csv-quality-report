# 0005: Same output bytes on every platform

- Status: accepted
- Deciders: rodrix91
- Issues: #116, #120

## Context

Until 0.14.0 CI ran only on Linux. The first Windows run (Python 3.11 and 3.13) failed 34 of 882 tests, for three reasons in the code:

- When stdout or stderr is redirected (a pipe, `> report.json`, a CI log), Python on Windows encodes with the ANSI code page (cp1252 on the GitHub runners), not UTF-8. A report with `guaraníes` came out as cp1252 bytes, which is not valid JSON text (RFC 8259 requires UTF-8) and differs from the `--json-output` file; a name outside the code page (`東京`) crashed the run with `UnicodeEncodeError` and a traceback.
- Text-mode streams and files on Windows write `\r\n` for every `\n`, so stdout and `--json-output` had different bytes from the same run on Linux or macOS.
- The CLI turned the input argument into a `Path` and reported `str(Path)`, so `examples/sample.csv` was reported as `examples\sample.csv` on Windows, in the `source` of the report and in error messages: the same command gave a different report, and pipelines keep reports as `--baseline` and compare them across machines.

## Decision

1. **UTF-8 and `\n` on stdout and stderr.** `main()` reconfigures both streams, when they are text wrappers, to `encoding="utf-8"` and `newline="\n"`, keeping their error handler. On Linux and macOS with a UTF-8 locale nothing changes. Streams that are not text wrappers (a `StringIO` installed by a caller) are left alone.
2. **`--json-output` is written with `newline="\n"`**, in the atomic path and in the in-place path for devices and pipes (ADR 0004).
3. **Paths are reported as given.** The CLI keeps the input argument as the text typed and `display_name()` returns a `str` unchanged; a path-like object gives its `os.fspath` text, as before. The reader carries that name next to the `Path` it opens, so the `source` of the report and the error messages that name the input show what the user wrote. Converting every path to `/` was tried first and rejected: it rewrote Windows paths the user typed with `\` and changed the messages of the Python API for `Path` arguments.
4. **Test data is byte-exact.** `.gitattributes` marks `tests/corpus/**` and `examples/**` as `-text`, so Git for Windows does not turn LF into CRLF on checkout, which changed a quoted multi-line field in the corpus.

## Consequences

- Output is always UTF-8, also when a user sets `PYTHONIOENCODING` to another encoding or runs under a non-UTF-8 locale; a tool that reads the report in the console code page must decode it as UTF-8.
- On Windows, a report printed to the console still shows correctly: Python writes to the console through its Unicode API whatever the encoding setting.
- On every platform, the CLI no longer normalizes the path it shows: `./data.csv` is reported as `./data.csv` (before: `data.csv`) and `dir//x.csv` as typed. Only the displayed name changes; the file opened is the same.
- Behavior that Windows itself lacks is skipped in its tests with the reason: POSIX permission bits (umask and `chmod` modes), named pipes (`os.mkfifo`), and symbolic links when the account may not create them. Hard links, `os.path.samefile` and `os.replace` run on every platform.

## Alternatives considered

| Alternative | Benefit | Cost / why not |
|---|---|---|
| Keep the platform defaults | No change for Windows users who expect CRLF | Reports differ between machines and crash on characters outside the code page. |
| Ask users to set `PYTHONUTF8=1` | No code change | Every pipeline must know about it, and CRLF and backslashes remain. |
| Write bytes to `sys.stdout.buffer` | Full control | Breaks callers that replace `sys.stdout` with a text stream, and stderr messages would still need the same handling. |
| Report every path with `/` (`as_posix`) | Same `source` on every platform | Rewrites a Windows path typed with `\`, and the Python API's messages for a `Path` would no longer match `str(path)`. |
| Normalize paths only in tests | Smaller diff | Hides a real difference: the same command would still write a different report on Windows. |
