# HANDOFF: csv-quality-report

- Repository path: /workspace/showcase/csv-quality-report (local only; nothing pushed, no remote, nothing created on GitHub)
- Branch: work/milestone-1 (default branch `main` holds only the first scaffolding commit)
- **HEAD SHA: a0c58bcd7a2b7675d2f3fe0732276f64e3d6c865** (this HANDOFF.md is written after that commit and is intentionally untracked, so it is not in the manifest)
- Status: prototype/alpha. License: pending owner decision (no LICENSE file; see LICENSE-PROPOSAL.md). OpenAPI: not_applicable (no HTTP).
- Python used: 3.13.5 (project requires >=3.11; only 3.13.5 was actually tested)

## Verified commands for CodeSentinel
Run on this box in a fresh clone + fresh venv (from the lockfile) from the repository root. The full install/test/lint/type/build sequence ran in a fresh clone of commit e198bc3; the only later commit (HEAD) changed CONTRIBUTING.md's secrets-scan snippet, and those scan commands were re-run on HEAD. Results are real.

| Step | Command | Result |
|---|---|---|
| install | `python3 -m venv .venv && . .venv/bin/activate` | ok |
| install (dev deps, exact pins) | `pip install -r requirements-dev.lock` | ok. `pip install -r requirements-dev.txt` in another fresh venv also ok; its `pip freeze` is identical to requirements-dev.lock |
| install (package) | `pip install -e .` | ok |
| tests | `python -m pytest -q` | 41 passed, 0 failed (0.22s) |
| lint | `ruff check .` | All checks passed (ruff 0.16.10) |
| format | `ruff format --check .` | 15 files already formatted |
| types | `mypy` | Success: no issues found in 11 source files (mypy 2.4.0, strict) |
| build | `python -m build --wheel` | Successfully built csv_quality_report-0.1.0-py3-none-any.whl (needs network for setuptools build isolation) |
| wheel smoke test | install wheel in a clean venv, run `csv-quality-report examples/tiny.csv --max-rows 1` | ok, exit 0 |
| sample command | `python -m csv_quality_report examples/sample.csv` | exit 0; output identical to README (also enforced by a test) |
| secrets scan (tracked files) | `git grep -EIn "<pattern in CONTRIBUTING.md>"` | no matches (exit 1); positive control with a fake `api_key = "x"` file matched |
| secrets scan (history) | `git log -p --all \| grep -EIn "<same pattern>"` | no matches (exit 1) |
| sdist build, pip-audit, coverage, CI workflow | | not_run |

Secrets scan pattern: AWS key ids, GitHub `ghp_` tokens, PEM private key headers, and `api_key|secret|token|password` followed by `:`/`=`. It is a simple grep, not a dedicated scanner.

## Proposed GitHub description and topics (for GitRank)
Description: Quick data-quality report for a CSV file: types, missing values, distinct counts, top values and duplicate rows. Standard-library Python CLI (prototype/alpha).

Topics (8): `python`, `cli`, `csv`, `data-quality`, `data-profiling`, `data-analysis`, `standard-library`, `pytest`

## Capability summary (for GitAura)
1. `python -m csv_quality_report data.csv [--format markdown|json] [--max-rows N]` profiles a local UTF-8 CSV: per column inferred type (int/float/bool/date/string), missing count and %, distinct count, numeric min/max, top 3 values; plus the dataset's duplicate row count.
2. Fails clearly with distinct nonzero exit codes (3 unreadable, 4 not UTF-8, 5 empty, 6 ragged rows, 2 usage); duplicate column names get deterministic _2/_3 suffixes.
3. Python 3.11+, no runtime dependencies, 41 pytest tests; limitations: loads the whole file in memory (no streaming), heuristic type inference, UTF-8 only.

## Not verified / caveats
- Only Python 3.13.5 was tested; 3.11 and 3.12 were not run.
- Not tested on Windows/macOS. No CI configured. No performance or large-file testing.
- Network was used only to download dev tools from PyPI for install/build; the tool itself makes no network calls.

## File manifest (tracked files at HEAD, sha256)
```text
3e861aeb236be27a3b09a357ae458e64a5a31ab17733249981792cfaea96686d  .gitignore
6216fe24d2e7358f5e2b983be88f0cc1af42e863cd7ebb2781bbe343124a7b2c  CONTRIBUTING.md
0a9ca443aa87ec8d282a93824e267982b6faa52b5f79a0a3ea8446891a22ce19  LICENSE-PROPOSAL.md
84584933f2a2c838787a20e7ac0c486b352eefd404fcffebb41e0f788657938e  README.md
df8e0eba971a01fa671e09cfaba25be563c7d3f044a03e919b2a39349fb8fbb0  docs/decisions/0001-architecture.md
765eb6bef0639221d201582e9da1148b38698a419cca29adf4d39fdf6423e9c4  examples/sample.csv
f1036be91dc016c6de3b52d42a3bb4f800ce6dbf9598e690c1ea4b95478ce2fd  examples/tiny.csv
7d3acb992403df89f020e36a3b6c8ffe423851641c85bb675d0878e53c998e5a  pyproject.toml
41857f0f66cc36c085ff7c57be8dff66934b8249487b831ac59a09c6699ed09f  requirements-dev.lock
c310517759244d306c1c9df84ab917cae0ace8c0918d16f3de59787a721dd970  requirements-dev.txt
29da554845294e68552f14c9520591a3582f626a7d034190e395e2f7303e167e  src/csv_quality_report/__init__.py
13a1a5b340cdcfc1902b62be90e508c7c71886000d5bf087e7854aadf09fb35e  src/csv_quality_report/__main__.py
76eed9b11ca6422ec401b0c94b46f45d616923f36b2ad90ee577447bffc42a4f  src/csv_quality_report/cli.py
41f9bb33c702cfe7db09dbee8c7fe03a647483614c782ca68d0bf863f13f4214  src/csv_quality_report/errors.py
afb076b2c53946b7908fde520fdb8a2d7a164a737a3c338fdbcff8606e2ed62b  src/csv_quality_report/inference.py
41962e2b3a3e0edf86a9f7595dba96d6e4f1f3b1f0c3d181ab3b48361d127bba  src/csv_quality_report/profile.py
8bf8fd0028460bda3c58af1f4e2edca9e23cc1376f86262da7e25a3d29e7222b  src/csv_quality_report/reader.py
c5436a29b53d4f2c05d5558c1bf8196d24ed8cb381ea9b31bff098957557ab70  src/csv_quality_report/render.py
1aba97b846bcb2f5f06b4dad9dc1d9fdecaed81fb4b0fd3592fc6c7db73287a7  tests/conftest.py
cd80bfda40077245d4b82401b55ac81e91870c9c89a5867606ce59ed178ed99d  tests/test_cli.py
4946d20d1504c0176e459f2f24b79a5b3789948ed1d4b3b715c89e894451b247  tests/test_inference.py
```
