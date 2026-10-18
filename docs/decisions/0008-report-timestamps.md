# 0008: Opt-in report timestamps and the baseline age gate

- Status: accepted
- Deciders: rodrix91
- Issues: #129 (follow-up to #91 and #101)

## Context

`--baseline` compares a run with an earlier JSON report, and the schema and drift gates (#91, #101, #127) turn that comparison into a pass/fail signal. None of them notices when the baseline itself stops moving: a CI artifact that expired and was restored from an old cache, or a job that keeps comparing every export with a report from months ago, passes every gate while comparing against the wrong thing.

Knowing the age of a baseline needs a time. Two places were available, and both had a cost:

- The JSON report had **no timestamp**, and that is a property the project relies on: the same input gives the same bytes on every run and every platform (ADR 0005), and the corpus, the guide and the README examples compare reports byte for byte. Pipelines also diff a report against the previous one, and a time that changes on every run makes every diff non-empty.
- The **file's modification time** says when the file was written to this disk, not when the data was profiled: downloading a CI artifact, `git checkout`, `cp` and cache restores all reset it, which is exactly the situation the gate is for.

## Decision

1. **`--record-time`, opt-in.** The flag adds a top-level `"generated_at"` right after `"source"`, the UTC time the run started in whole seconds (`2026-10-16T04:06:00Z`), to the report on stdout with `--format json` and to the `--json-output` file. Without the flag the key is absent and reports are byte-identical to earlier releases. Markdown has no stamp, so the flag needs a JSON report (otherwise a usage error: it would do nothing).
2. **`SOURCE_DATE_EPOCH` replaces the clock** when set, following the reproducible-builds convention, for the stamp and for the age gate alike, so golden files, the corpus and rebuilt pipelines can reproduce both exactly. An empty value counts as unset; anything other than a whole number of seconds is a usage error (exit 2), checked before the file is read and only when one of the two options needs the clock.
3. **`--max-baseline-age DURATION`**, with `--baseline` (a usage error without it). `DURATION` is a positive whole number with `s`, `m`, `h`, `d` or `w` (`36h`, `7d`); no fractions, other units or bare numbers, so `7` is never read as seconds or days by accident. The age is the time of the run minus the baseline's `generated_at`, in whole seconds (fractions dropped); an age equal to the limit passes. It is a file-level `baseline_age` check, `limit` and `value` in seconds, with the baseline's stamp as `generated_at`. The message spells the age out: `the baseline is 9 days 4 hours old (generated 2026-10-07T00:00:00Z; limit 7 days)`.
4. **No stamp, no age, never a fallback.** A baseline without `generated_at` fails the gate and says how to fix it (`write it with --record-time`); a value that is not exactly the form the tool writes fails the same way and quotes it. The modification time is never used (see Context), and an unstamped baseline keeps working for every other comparison and gate.
5. **Clock skew.** A stamp up to 5 minutes ahead of the clock counts as 0 seconds old, since two machines rarely agree to the second; further ahead fails as `the baseline was generated in the future: ...`, because a negative age means a wrong clock or an edited report, not a fresh baseline.
6. **Independent options.** `--max-baseline-age` reads the baseline's stamp and does not stamp the current run; a pipeline that wants its next baseline stamped adds `--record-time`. One reading of the clock serves both in a run, so a run that does both agrees with itself.
7. **Python API.** `baseline_age_check(comparison, max_age, now)` in `csv_quality_report.checks`, with `now` passed in so callers and tests need no real clock; `Comparison` gains `baseline_generated_at`, and `render_json()` gains `generated_at`. The clock helpers live in `csv_quality_report.clock`. None of them is exported from the package root, like the other baseline gates.

## Consequences

- A scheduled pipeline can fail when its baseline is older than its schedule allows, with a time that survives artifact downloads and cache restores.
- Stamped reports differ on every run, by one line. Pipelines that diff reports can leave the flag off and still use every other gate.
- The first run with `--max-baseline-age` fails until the baseline has been rewritten with `--record-time`. This is deliberate: an unknown age is not a fresh one.
- Whether `generated_at` should become the default in a later minor release (breaking byte-identical reports once) stays open; nothing in this design prevents it. (Resolved on 2026-10-18, see the update below.)

## Alternatives considered

| Alternative | Benefit | Cost / why not |
|---|---|---|
| Always write `generated_at` | Every baseline can be checked | Breaks byte-identical reports, the corpus, the guide and report diffs for everyone, for a gate few runs use. Left as an open question for a later release (declined on 2026-10-18; see the update below). |
| Use the baseline file's modification time | No format change | Wrong in exactly the cases the gate is for (downloaded artifacts, restored caches, checkouts). |
| Accept any ISO 8601 time (offsets, fractions) | Hand-edited baselines work | The stamp is written by this tool; anything else means the report was edited or produced elsewhere, which should be visible. |
| `--max-baseline-age` stamps the current run too | One flag | Changes the bytes of a report as a side effect of a gate; the two concerns are kept apart. |
| Fall back to "pass" for unstamped baselines | Smooth adoption | An age gate that passes when it cannot measure the age gives false confidence. |

## Update (2026-10-18): `generated_at` stays opt-in

The open question in Consequences is decided: `generated_at` stays opt-in (`--record-time`), and no future release writes it by default.

- Byte-identical reports remain the default. The corpus, the guide samples, the README samples and pipelines that diff a report against the previous one rely on them.
- The pipelines that need the stamp now have a documented path. The GitHub Action's `report-path` and `baseline` inputs (#138) keep each day's report as the next baseline, and the README and the guide show `--record-time` with `--max-baseline-age`. The freshness gate `--max-age` (ADR 0009) checks the data itself and needs no stamp.
- A pipeline that forgets `--record-time` is not silently wrong: `--max-baseline-age` fails on an unstamped baseline and says how to stamp it (decision 4 above).
