# Related tools

The three active projects in this GitHub portfolio are intentionally complementary:

1. **csv-quality-report** profiles and validates raw CSV extracts.
2. **ops-field-brief** performs fast operational completeness and concentration checks.
3. **inventory-policy-lab** turns validated demand history into inventory-policy analysis and replay.

## ops-field-brief

[ops-field-brief](https://github.com/rodrix91/ops-field-brief) is a small standard-library Python CLI for five practical questions about one operational CSV:

- Are required fields filled? Empty cells and common missing tokens such as `NA`, `N/A`, `null`, `none`, `s/d`, `s.d.`, `N/D`, `N.D.`, and `-` count as missing.
- Does the business key repeat? Single-column and composite keys such as `order_id,line_id` are supported.
- Which groups account for the rows?
- Does one group dominate more of the extract than allowed? `--max-group-share` adds an opt-in concentration gate used with `--group`.
- Does the extract contain at least the expected number of rows? `--min-rows` adds an opt-in row-count gate.

Use `csv-quality-report` for broader profiling and pipeline-oriented quality gates such as types, ranges, allowed values, uniqueness, freshness, schema changes, and baseline drift. Use `ops-field-brief` when the question is operational completeness and concentration.

`--delimiter` accepts `comma` (default), `semicolon`, `tab`, `pipe`, or `auto`. Automatic detection is intentionally conservative and exits with a clear error rather than guessing when the separator is ambiguous.

`--encoding` defaults to `utf-8`. A UTF-8 BOM is stripped, including on stdin. For Windows spreadsheet exports, `cp1252` or `latin-1` can be selected explicitly.

The CLI also supports stdin, JSON or Markdown output, configurable missing-rate and duplicate limits, and a configurable top-group count.

Status: **0.3.0 with additional Unreleased work**. CI runs **63 tests** on Python 3.10 through 3.13 on Ubuntu, with Python 3.10 and 3.13 also validated on Windows and macOS. A dedicated quality job enforces branch coverage of at least 90%, Ruff lint/format checks, and mypy. Packaging is smoke-tested in a clean environment. See [CONTRIBUTING.md](https://github.com/rodrix91/ops-field-brief/blob/main/CONTRIBUTING.md).

## inventory-policy-lab

[inventory-policy-lab](https://github.com/rodrix91/inventory-policy-lab) is a standard-library Python toolkit and CLI that turns per-SKU demand history into reviewable inventory-policy analysis.

It includes:

- ABC-XYZ classification and Syntetos-Boylan demand-pattern classification.
- Backtested forecasts scored with MASE, including naive, moving average, SES, Croston, SBA, and opt-in damped Holt / Holt-Winters models.
- Normal-formula or bootstrap safety stock.
- Reorder points, EOQ, and `(s, Q)`, `(R, S)`, and `(R, s, S)` policy replay.
- Out-of-sample and rolling-origin replay.
- Optional dynamic seasonal levels, residual bootstrap, configurable refit cadence, cost accounting, and cost-oriented level search.

Use `csv-quality-report` first to verify that the demand extract is structurally sound, then use `inventory-policy-lab` to study policy choices. `ops-field-brief` can sit between them when an operations team also wants fast checks on required fields, repeated keys, row counts, or counterparty concentration.

Status: **0.10.0 alpha**. The project has **403 tests**, 100% line and branch coverage, Ruff, strict mypy, and cross-platform CI on supported Python versions. Its README documents formulas, assumptions, limitations, worked examples, and empirical comparisons so the output remains auditable rather than a black box.
