# 0010: Options files (`--options-file`) with a small, literal syntax

- Status: accepted
- Deciders: rodrix91
- Issues: #323

## Context

A pipeline that checks a scheduled export needs a long command line: the reading options of the export (`--delimiter auto --decimal-comma --thousands dot --date-order dmy --na s/d,#N/A`) and a dozen gates (`--require-columns`, `--unique-key`, `--range`, `--require-when`, `--forbid-lost-zeros`, ...). That list lived in a shell script or a workflow file, mixed with the paths, which has two costs:

- The same checks could not be shared between a local run, a cron job and CI without copying them, and the copies drift.
- Spanish exports are full of column names with spaces (`Fecha entrega`, `Código postal`, `Nro. factura`). In a shell they need quoting that changes between Bash, PowerShell and `cmd.exe`, and the GitHub Action, which splits `args` on whitespace, cannot pass them at all.

## Decision

1. **`--options-file FILE`**, repeatable. Each occurrence is replaced by the tokens of the file **in place**, before `argparse` sees the command line, so an option written after it overrides a single-value option of the file and repeatable options add up, exactly as if the tokens had been typed there. Tokens after a bare `--` are positional and are not expanded.
2. **Recognised the way `argparse` reads it.** `--options-file=FILE` and unambiguous abbreviations (`--opt FILE`) are expanded too; whether a prefix is unambiguous is computed from the parser's own option list, so a future option starting with the same letters makes the prefix ambiguous instead of silently expanding it. The option stays registered in the parser, so `--help` lists it.
3. **A small syntax, chosen to need no escaping in this tool's values:**
   - one or more options per line, separated by spaces or tabs (a no-break space is text, as in a column name);
   - single or double quotes group words and are removed; inside one kind, the other is literal; a quoted part joins the text next to it; `""` is an empty value;
   - a line whose first non-blank character is `#` is a comment, and there are **no inline comments**, so `--na #N/A` works;
   - **backslashes are literal**, so `--pattern 'CUIT=\d{2}-\d{8}-\d'` and Windows paths are written as they are;
   - UTF-8 with an optional BOM; `\r\n` line endings are accepted.
4. **Strict errors, as usage errors (exit code 2), naming the file and the line:** a file that cannot be read, invalid UTF-8 (with the byte), an unclosed quote, control characters other than tab (the same set the Action refuses in `args`), a file over 1 MiB (most likely a CSV passed by mistake), `--options-file` inside a file (no includes) and a bare `--` (it would end the options of the whole command line). `-` is refused because standard input is the CSV.
5. **The GitHub Action refuses it for now.** The Action refuses `--baseline`, `--json-output`, `--help` and `--version` in `args` and `baseline-args`; a file could carry any of them. Until the Action reads the file itself (path kept inside the workspace, contents checked with the same rules), every token starting with `--o` is refused there, which is exact while `--options-file` is the only option with that prefix (a test pins this).

## Consequences

- A versioned `checks/export.opts` file is the single source of the checks of an export, and column names with spaces are written once, in one quoting style, on every platform.
- Runs without the option are unchanged: the expansion returns the same tokens.
- The syntax is not a shell: no variables, no escapes, no inline comments. A value that must contain both kinds of quote cannot be written; no option of the tool needs that today.
- The Action cannot use column names with spaces yet; that is the follow-up.

## Alternatives considered

| Alternative | Benefit | Cost / why not |
|---|---|---|
| `argparse` `fromfile_prefix_chars="@"` | Built in | One argument per line (no `--require-when NAME COLUMN=VALUES` on a line), no comments, no quotes, and `@` would make a CSV path starting with `@` unreadable. |
| `shlex.split` per line | Familiar shell rules | Backslashes escape (`\d` must be written `\\d`), `#` needs `commenters` and then breaks `--na #N/A`, and Windows paths need doubling. |
| A TOML or YAML config file | Structured, typed | A second way to spell every option, kept in sync with the CLI by hand; YAML needs a dependency (TOML is read-only in the standard library). Options files reuse the CLI exactly. |
| Allow includes | Shared fragments | Cycles, relative-path rules and harder errors, for a file of a few lines. |
