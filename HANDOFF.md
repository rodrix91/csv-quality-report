# HANDOFF: csv-quality-report

- Repository: /workspace/showcase/csv-quality-report (local only; no remote, nothing pushed, nothing created on GitHub)
- Branch: `work/milestone-1` (`main` holds only the first scaffolding commit)
- **Verified commit: `1f72d0f52b48633d7a275b717c12c84f3d041d96`**. HEAD is the commit right after it and changes only this file (`HANDOFF.md`), so every other file is identical. Get HEAD with `git rev-parse HEAD`; a file cannot contain the hash of the commit that adds it.
- Status: prototype/alpha. License: pending owner decision (no LICENSE file; see LICENSE-PROPOSAL.md). OpenAPI: not_applicable (no HTTP).
- Tracked files: 24 = the 23 listed in the manifest below + this file.
- History note: an early, stale revision of this file was committed by accident in `c960391` (via `git add -A`); `2d95681` replaced it with a placeholder and later revisions replace that. No history was rewritten.

## Fixes since the first audit (CodeSentinel, a0c58bcd)
| Defect | Fix |
|---|---|
| D1 tests failed when only the lock was installed | subprocess tests set `PYTHONPATH=src` (fixture `cli_env` in tests/conftest.py); README/CONTRIBUTING document that `pip install -e .` is optional |
| D2 5000-digit integer crashed | `inference._is_int` catches `ValueError`; column degrades to `string`; tests added |
| D3 wheel listed LICENSE-PROPOSAL.md | `license-files = []` in pyproject; built wheel has no license file and no `License-File` header |
| D4 `1e999` printed as `Infinity` in JSON | non-finite floats make the column `string`; JSON uses `allow_nan=False`; tests added; documented in README |
| D5 lock without hashes, unpinned build backend | `setuptools==84.0.0` in build-system; `requirements-dev.lock` generated with hashes by `uv pip compile --generate-hashes` (uv 0.12.22) |
| D6 HANDOFF untracked, wrong file count, verification not at HEAD | HANDOFF committed; 21-file manifest recomputed; full sequence re-run at the verified commit |

Second audit (CodeSentinel, bbaaba02: approved with 3 minor defects):
| Defect | Fix |
|---|---|
| N1 sdist lacked tests/conftest.py | `MANIFEST.in` with `include tests/conftest.py`; sdist rebuilt and listed: contains tests/conftest.py, tests/test_render.py and MANIFEST.in (27 entries at that time). The sdist initially lacked `examples/` (see N5) |
| N2 history scan excluded all of HANDOFF.md | exclusion removed; the documented command now filters only the one known line (`grep -vF 'positive control with a fake'`). Without the filter exactly 2 lines match (the stale line in c960391 and its removal in 2d95681); with it, 0 |
| N3 no direct test of render_json with inf/nan | `tests/test_render.py`: 3 non-finite cases must raise ValueError, plus a strict-JSON check. Mutation: changing `allow_nan=False` to `True` makes 3 of the 4 tests fail; restored, all pass |

Third audit (CodeSentinel, ec27c724: approved_for_publication_draft with non-blocking findings):
| Finding | Status |
|---|---|
| N5 sdist lacked examples/ (unpacked sdist: 1 failed, 53 passed) | fixed: `graft examples` added to `MANIFEST.in`. Unpacked the old sdist in a clean dir with a fresh lock-only venv: 1 failed, 53 passed (reproduced). Same for the new sdist: 54 passed. Wheel content unchanged (13 members, identical names and sha256 vs ec27c72); neither sdist nor wheel contains any license file |
| N6 | known limitation (no code change): the packaged README links to `LICENSE-PROPOSAL.md`, which is not shipped in the sdist or wheel, so that link is dead on package indexes |
| N7 | known limitation (no code change): the history-scan filter in CONTRIBUTING.md (`grep -vF 'positive control with a fake'`) matches by substring, so any other line containing that phrase would also be hidden |
| N8 | correction: `tests/test_render.py` is +45 lines, not the +42 stated in the previous report |

## Verified commands for CodeSentinel
Run in a fresh `git clone` + fresh venv at the verified commit, installing ONLY from the lock (no `pip install -e .`; the package was confirmed not installed). All results are real. Python 3.13.5 was the primary interpreter; the same sequence was also run with 3.11.17 and 3.12.15 (same results).

| Step | Command | Result |
|---|---|---|
| venv | `python3 -m venv .venv && . .venv/bin/activate` | ok |
| install | `pip install --require-hashes -r requirements-dev.lock` | ok on 3.13 at the verified commit (and on 3.11, 3.12 earlier); 14 packages; no editable install |
| tests | `python -m pytest -q` | 54 passed, 0 failed (about 0.23s) on 3.13.5 at the verified commit (50 passed on 3.11.17 and 3.12.15 at the earlier commit 2d95681; not re-run on them after the new tests) |
| lint | `ruff check .` | All checks passed (ruff 0.16.10) |
| format | `ruff format --check .` | 17 files already formatted |
| types | `mypy` (strict; src and tests) | Success: no issues found in 12 source files (mypy 2.4.0) |
| build | `python -m build --wheel` | built csv_quality_report-0.1.0-py3-none-any.whl (downloads setuptools==84.0.0 from PyPI; that download is not hash-checked) |
| sdist | `python -m build --sdist`, then `tar tzf dist/*.tar.gz` | built csv_quality_report-0.1.0.tar.gz; lists tests/conftest.py, tests/test_render.py, MANIFEST.in, examples/sample.csv, examples/tiny.csv; no license file |
| sdist unpacked test | untar the sdist in a clean dir; new venv; `pip install --require-hashes -r requirements-dev.lock`; `python -m pytest -q` inside the unpacked dir (package not installed) | 54 passed |
| wheel metadata | inspect the wheel zip | no license file inside, no License-File header |
| wheel smoke test | new clean venv, `pip install dist/*.whl`, then `csv-quality-report examples/tiny.csv --max-rows 1` and `python -m csv_quality_report examples/sample.csv` | both exit 0; sample output identical to the source run |
| README sample | `PYTHONPATH=src python3 -m csv_quality_report examples/sample.csv` | exit 0; output is contained verbatim in README.md (a test also enforces this) |
| secrets scan, tracked files | first command in the "Local secrets scan" block of CONTRIBUTING.md | no matches (exit 1) |
| secrets scan, history | second command in the same block (filters one known line, see history note) | no matches (exit 1) |

Earlier checks, not repeated at the verified commit: `pip install -r requirements-dev.txt` in a fresh venv gave a `pip freeze` identical to the old unhashed lock (before the lock was regenerated).

Scan pattern: AWS key ids, GitHub personal-token prefixes, PEM private-key headers, and key/secret/token/password names followed by a colon or equals sign. It is a plain grep, not a dedicated scanner.

not_run: coverage, pip-audit, CI workflow, Windows/macOS, large-file/performance tests; Python 3.11/3.12 re-run after the latest commits (last run on them: 50 tests at 2d95681).

## Proposed GitHub description and topics (for GitRank)
Description: Quick data-quality report for a CSV file: types, missing values, distinct counts, top values and duplicate rows. Standard-library Python CLI (prototype/alpha).

Topics (8): `python`, `cli`, `csv`, `data-quality`, `data-profiling`, `data-analysis`, `standard-library`, `pytest`

## Capability summary (for GitAura)
1. `python -m csv_quality_report data.csv [--format markdown|json] [--max-rows N]` profiles a local UTF-8 CSV: per column inferred type (int/float/bool/date/string), missing count and %, distinct count, numeric min/max, top 3 values; plus the dataset's duplicate row count.
2. Fails clearly with distinct nonzero exit codes (3 unreadable, 4 not UTF-8, 5 empty, 6 ragged rows, 2 usage); duplicate column names get deterministic _2/_3 suffixes; unrepresentable numbers (huge integers, 1e999) degrade to string and JSON output is always standard JSON.
3. Python 3.11+, no runtime dependencies, 54 pytest tests; limitations: loads the whole file in memory (no streaming), heuristic type inference, UTF-8 only.

## Not verified / caveats
- Windows/macOS not tested. No CI. No large-file or performance testing. No coverage measurement.
- Network was used only to download dev tools and the build backend from PyPI; the tool itself makes no network calls.
- The hashed lock was generated with uv and verified with pip `--require-hashes`; the build-isolation setuptools download is pinned by version only.

## File manifest (23 tracked files, sha256, excluding this file)
```text
3e861aeb236be27a3b09a357ae458e64a5a31ab17733249981792cfaea96686d  .gitignore
e2602e46046636d10f7dae3a31d9aaf75b9f792de72e59526d27d7d4609703d5  CONTRIBUTING.md
0a9ca443aa87ec8d282a93824e267982b6faa52b5f79a0a3ea8446891a22ce19  LICENSE-PROPOSAL.md
b2b7115a8f260fc4888496c959d6efc93f258aa96554f39c46491b18d2a0b501  MANIFEST.in
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
c05c5da45093ae103c7a5a50e21c022c073e59596dcac94f40906d0ed52e1b86  tests/test_render.py
```
