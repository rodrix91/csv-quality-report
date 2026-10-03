# HANDOFF: csv-quality-report

- Repository: /workspace/showcase/csv-quality-report (local only; no remote, nothing pushed, nothing created on GitHub)
- Branch: `work/milestone-1` (`main` holds only the first scaffolding commit)
- **Verified commit: `2d95681cb4b759d7fbcb9a7f632e97248edc8215`**. HEAD is the commit right after it and changes only this file (`HANDOFF.md`), so every other file is identical. Get HEAD with `git rev-parse HEAD`; a file cannot contain the hash of the commit that adds it.
- Status: prototype/alpha. License: pending owner decision (no LICENSE file; see LICENSE-PROPOSAL.md). OpenAPI: not_applicable (no HTTP).
- Tracked files: 22 = the 21 listed in the manifest below + this file.
- History note: an early, stale revision of this file was committed by accident in `c960391` (via `git add -A`); `2d95681` replaced it with a placeholder and this version replaces that. No history was rewritten.

## Fixes since the first audit (CodeSentinel, a0c58bcd)
| Defect | Fix |
|---|---|
| D1 tests failed when only the lock was installed | subprocess tests set `PYTHONPATH=src` (fixture `cli_env` in tests/conftest.py); README/CONTRIBUTING document that `pip install -e .` is optional |
| D2 5000-digit integer crashed | `inference._is_int` catches `ValueError`; column degrades to `string`; tests added |
| D3 wheel listed LICENSE-PROPOSAL.md | `license-files = []` in pyproject; built wheel has no license file and no `License-File` header |
| D4 `1e999` printed as `Infinity` in JSON | non-finite floats make the column `string`; JSON uses `allow_nan=False`; tests added; documented in README |
| D5 lock without hashes, unpinned build backend | `setuptools==84.0.0` in build-system; `requirements-dev.lock` generated with hashes by `uv pip compile --generate-hashes` (uv 0.12.22) |
| D6 HANDOFF untracked, wrong file count, verification not at HEAD | HANDOFF committed; 21-file manifest recomputed; full sequence re-run at the verified commit |

## Verified commands for CodeSentinel
Run in a fresh `git clone` + fresh venv at the verified commit, installing ONLY from the lock (no `pip install -e .`; the package was confirmed not installed). All results are real. Python 3.13.5 was the primary interpreter; the same sequence was also run with 3.11.17 and 3.12.15 (same results).

| Step | Command | Result |
|---|---|---|
| venv | `python3 -m venv .venv && . .venv/bin/activate` | ok |
| install | `pip install --require-hashes -r requirements-dev.lock` | ok on 3.11, 3.12, 3.13 (14 packages; no editable install) |
| tests | `python -m pytest -q` | 50 passed, 0 failed (about 0.25s) on 3.11, 3.12 and 3.13 |
| lint | `ruff check .` | All checks passed (ruff 0.16.10) |
| format | `ruff format --check .` | 16 files already formatted |
| types | `mypy` (strict; src and tests) | Success: no issues found in 11 source files (mypy 2.4.0) |
| build | `python -m build --wheel` | built csv_quality_report-0.1.0-py3-none-any.whl (downloads setuptools==84.0.0 from PyPI; that download is not hash-checked) |
| wheel metadata | inspect the wheel zip | no license file inside, no License-File header |
| wheel smoke test | new clean venv, `pip install dist/*.whl`, then `csv-quality-report examples/tiny.csv --max-rows 1` and `python -m csv_quality_report examples/sample.csv` | both exit 0; sample output identical to the source run |
| README sample | `PYTHONPATH=src python3 -m csv_quality_report examples/sample.csv` | exit 0; output is contained verbatim in README.md (a test also enforces this) |
| secrets scan, tracked files | first command in the "Local secrets scan" block of CONTRIBUTING.md | no matches (exit 1) |
| secrets scan, history | second command in the same block (excludes HANDOFF.md, see history note) | no matches (exit 1) |

Earlier checks, not repeated at the verified commit: `pip install -r requirements-dev.txt` in a fresh venv gave a `pip freeze` identical to the old unhashed lock (before the lock was regenerated).

Scan pattern: AWS key ids, GitHub personal-token prefixes, PEM private-key headers, and key/secret/token/password names followed by a colon or equals sign. It is a plain grep, not a dedicated scanner.

not_run: sdist build, coverage, pip-audit, CI workflow, Windows/macOS, large-file/performance tests.

## Proposed GitHub description and topics (for GitRank)
Description: Quick data-quality report for a CSV file: types, missing values, distinct counts, top values and duplicate rows. Standard-library Python CLI (prototype/alpha).

Topics (8): `python`, `cli`, `csv`, `data-quality`, `data-profiling`, `data-analysis`, `standard-library`, `pytest`

## Capability summary (for GitAura)
1. `python -m csv_quality_report data.csv [--format markdown|json] [--max-rows N]` profiles a local UTF-8 CSV: per column inferred type (int/float/bool/date/string), missing count and %, distinct count, numeric min/max, top 3 values; plus the dataset's duplicate row count.
2. Fails clearly with distinct nonzero exit codes (3 unreadable, 4 not UTF-8, 5 empty, 6 ragged rows, 2 usage); duplicate column names get deterministic _2/_3 suffixes; unrepresentable numbers (huge integers, 1e999) degrade to string and JSON output is always standard JSON.
3. Python 3.11+, no runtime dependencies, 50 pytest tests; limitations: loads the whole file in memory (no streaming), heuristic type inference, UTF-8 only.

## Not verified / caveats
- Windows/macOS not tested. No CI. No large-file or performance testing. No coverage measurement.
- Network was used only to download dev tools and the build backend from PyPI; the tool itself makes no network calls.
- The hashed lock was generated with uv and verified with pip `--require-hashes`; the build-isolation setuptools download is pinned by version only.

## File manifest (21 tracked files, sha256, excluding this file)
```text
3e861aeb236be27a3b09a357ae458e64a5a31ab17733249981792cfaea96686d  .gitignore
b82826ef0ffa0ff925da0ff0d68bce8f3a266b842b93e9c76fcfdac839d0cf7d  CONTRIBUTING.md
0a9ca443aa87ec8d282a93824e267982b6faa52b5f79a0a3ea8446891a22ce19  LICENSE-PROPOSAL.md
cd69c52add2509257b81728c72e2e2bbc32d9fd01d4fbd55124aa556abccf7b4  README.md
df8e0eba971a01fa671e09cfaba25be563c7d3f044a03e919b2a39349fb8fbb0  docs/decisions/0001-architecture.md
765eb6bef0639221d201582e9da1148b38698a419cca29adf4d39fdf6423e9c4  examples/sample.csv
f1036be91dc016c6de3b52d42a3bb4f800ce6dbf9598e690c1ea4b95478ce2fd  examples/tiny.csv
29612c012ab1d6855818d60df317036c14baaf8fa927efa86ca4d079f924128a  pyproject.toml
e5707bd45496df79cd59c7210e06cc364d07456e028a6d4a96f198a2397ddaec  requirements-dev.lock
c310517759244d306c1c9df84ab917cae0ace8c0918d16f3de59787a721dd970  requirements-dev.txt
29da554845294e68552f14c9520591a3582f626a7d034190e395e2f7303e167e  src/csv_quality_report/__init__.py
13a1a5b340cdcfc1902b62be90e508c7c71886000d5bf087e7854aadf09fb35e  src/csv_quality_report/__main__.py
76eed9b11ca6422ec401b0c94b46f45d616923f36b2ad90ee577447bffc42a4f  src/csv_quality_report/cli.py
41f9bb33c702cfe7db09dbee8c7fe03a647483614c782ca68d0bf863f13f4214  src/csv_quality_report/errors.py
85d9358523fcd32c47ed98d8ea4f4beea6830ecf5b1d21feceb81893744bf8ae  src/csv_quality_report/inference.py
41962e2b3a3e0edf86a9f7595dba96d6e4f1f3b1f0c3d181ab3b48361d127bba  src/csv_quality_report/profile.py
8bf8fd0028460bda3c58af1f4e2edca9e23cc1376f86262da7e25a3d29e7222b  src/csv_quality_report/reader.py
773209fda2980874342d1f4f023e28e0d03076e50349fb27adbf8c9bc7637993  src/csv_quality_report/render.py
f272e40fb74ac55569a772549102f8aecba83711db6a6864c26b2fda9c304159  tests/conftest.py
816bde67da49fc4abe7d50572b45463d161401f61f2b556b3a399ac6b99bd854  tests/test_cli.py
5e365fce6d2282f76e463956756647bae036b1f0ad7e8a63a735acb19c342d37  tests/test_inference.py
```
