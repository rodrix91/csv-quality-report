# 0004: Write `--json-output` atomically

- Status: accepted
- Deciders: rodrix91
- Issue: #107

## Context

Until 0.13.0 the CLI wrote `--json-output FILE` with `Path.write_text`, which truncates `FILE` and then writes the new report into it. A process killed halfway, a full disk or any write error left `FILE` empty or holding half a JSON document, and the report of the previous run was already gone. Pipelines often keep that file and pass it as the next run's `--baseline`, so one interrupted run also broke the following one (exit code 3, "not a JSON report").

## Decision

1. **Temporary file plus rename.** `output.write_atomic()` writes the report to a new file in the target's directory (`.<name>.<random>.tmp`, created with `O_CREAT | O_EXCL`), flushes it and calls `fsync`, then moves it onto the target with `os.replace`. In the same directory both paths are on the same file system, where the rename is atomic on POSIX and on Windows: readers see the old report or the new one, never a mix.
2. **Clean up on any failure.** If creating, writing, syncing, changing the mode or renaming fails, or the run is interrupted (`KeyboardInterrupt` included), the temporary file is removed and the error propagates. The CLI keeps exit code 9 and the message `cannot write 'FILE': <reason>`; the previous `FILE` is left byte for byte, and a new `FILE` is not created.
3. **Keep what the old write kept.** A new file gets the permissions the umask gives (`os.open` with mode `0o666`, as `open()` does); an existing file keeps its permission bits, copied to the temporary file before the rename. A symbolic link is written through: the temporary file goes next to the link's resolved target and replaces that file, so the link still works.
4. **Paths that cannot be replaced are written in place.** An existing target that is not a regular file (`/dev/stdout`, `/dev/null`, a named pipe) is written directly, as before: renaming over a device node or a pipe would be wrong, and these targets hold no earlier report to protect. A directory still fails with exit code 9.

## Consequences

- A hard-linked target is replaced by a new file: the path given to `--json-output` gets the new report, other names of the old file keep the old one (atomic replacement cannot update every name of a file).
- The owner and group of an existing file are not copied; the new file belongs to the user who runs the tool.
- The directory must be writable. A writable file in a read-only directory, which the old in-place write could overwrite, now fails with exit code 9 and leaves the file unchanged. Falling back to an in-place write would silently drop the guarantee.
- A crash between creating the temporary file and removing it (power loss, `SIGKILL`) can leave a hidden `.<name>.<random>.tmp` file next to the target; it never replaces or damages the report.
- The directory itself is not synced after the rename, so after a power loss the rename may be lost and the old report found instead; either way the file holds one complete report.

## Alternatives considered

| Alternative | Benefit | Cost / why not |
|---|---|---|
| Keep `write_text` | Simplest; keeps hard links, owner and group | A failure leaves a truncated report and destroys the previous one. |
| `tempfile.NamedTemporaryFile(dir=..., delete=False)` | Standard helper | Creates the file with mode `0o600`, so the umask no longer decides the permissions of new reports; the name and mode handling ends up the same size. |
| Temporary file in the system temp directory | Works when the target directory is read-only | It may be another file system, where `os.replace` fails or is not atomic. |
| Write a backup copy, then write in place | Keeps hard links | Two full writes; a crash still leaves a half-written `FILE` for readers. |
