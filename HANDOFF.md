# HANDOFF: csv-quality-report

- Repository: /workspace/showcase/csv-quality-report. Published at https://github.com/rodrix91/csv-quality-report (public, default branch `main`, license detected by GitHub as MIT). When this revision was prepared (2026-10-03, about 19:30 La Paz time) `git fetch origin` and `git ls-remote` gave `origin/main` = `1471ff4cd93a9948ab2b08640aaa9e6d67350442` (34 commits; the last one, `1471ff4`, added `.github/dependabot.yml` and was authored by PulseOps <pulseops@localhost>, per `git log`). `work/milestone-1` was fast-forwarded to that commit before this file was edited. Whether this revision of the file has itself been pushed is deliberately not recorded here (it would be stale as soon as it is pushed): check with `git status -sb` and `git ls-remote origin main`. This agent never pushes unless explicitly told to.
- Branches (verified with git on 2026-10-03): `work/milestone-1` is `origin/main` plus the single commit that edits this file. The local `main` branch is still the first scaffolding commit `154e9ab`; it is an ancestor of `origin/main` (`git merge-base --is-ancestor main origin/main` is true) and is simply 33 commits behind. It was not touched.
- **Verified commit: `1471ff4cd93a9948ab2b08640aaa9e6d67350442`** (= `origin/main` when prepared). HEAD is that commit plus one commit that changes only `HANDOFF.md`, so every other file is identical to the verified commit (`git diff 1471ff4c HEAD --stat` lists only this file). A file cannot contain the hash of the commit that adds it.
- Status: prototype/alpha. License: MIT, Copyright (c) 2026 Rodrigo Pantoja Navajas (see License decision below). OpenAPI: not_applicable (no HTTP).
- Tracked files: 25 = the 24 listed in the manifest below + this file (the manifest now includes `.github/dependabot.yml`).
- History note: an early, stale revision of this file was committed by accident in `c960391` (via `git add -A`); `2d95681` replaced it with a placeholder and later revisions replace that. No history was rewritten.

## Fixes since the first audit (CodeSentinel, a0c58bcd)
| Defect | Fix |
|---|---|
| D1 tests failed when only the lock was installed | subprocess tests set `PYTHONPATH=src` (fixture `cli_env` in tests/conftest.py); README/CONTRIBUTING document that `pip install -e .` is optional |
| D2 5000-digit integer crashed | `inference._is_int` catches `ValueError`; column degrades to `string`; tests added |
| D3 wheel listed the license proposal file | `license-files = []` was set while no license was chosen (superseded by the MIT decision below) |
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
| N5 sdist lacked examples/ (unpacked sdist: 1 failed, 53 passed) | fixed: `graft examples` added to `MANIFEST.in`. Unpacked the old sdist in a clean dir with a fresh lock-only venv: 1 failed, 53 passed (reproduced). Same for the new sdist: 54 passed. Wheel content unchanged (13 members, identical names and sha256 vs ec27c72); at that commit neither artifact contained a license file (changed by the MIT decision below) |
| N6 | resolved by the MIT decision: `LICENSE-PROPOSAL.md` was removed and the README now links to `LICENSE`, which ships in both sdist and wheel (a relative link may still not resolve on a package index page, but the file is in the package and the metadata carries the license) |
| N7 | known limitation (no code change): the history-scan filter in CONTRIBUTING.md (`grep -vF 'positive control with a fake'`) matches by substring, so any other line containing that phrase would also be hidden |
| N8 | correction: `tests/test_render.py` is +45 lines, not the +42 stated in the previous report |

## License decision (MIT) and fourth round of changes
Rodrigo approved the MIT proposal (his words: "esta perfecto la propuesta MIT" and "ustedes tomen todas las decisiones"), holder "Rodrigo Pantoja Navajas", year 2026. Changes, each in its own commit after 820a083:
| Item | Change |
|---|---|
| LICENSE | added; body compared with the SPDX MIT text (whitespace-normalized): identical; first lines are `MIT License` and `Copyright (c) 2026 Rodrigo Pantoja Navajas` |
| pyproject | `license = "MIT"` and `license-files = ["LICENSE"]` (PEP 639, works with setuptools==84.0.0). Wheel metadata: `License-Expression: MIT`, `License-File: LICENSE`; wheel has `dist-info/licenses/LICENSE`; sdist has `LICENSE`; both byte-identical to the repo's LICENSE |
| Docs | README "License" section points to LICENSE; CONTRIBUTING license section says contributions are under MIT |
| LICENSE-PROPOSAL.md | removed with `git rm` (decision recorded here); no remaining references outside this file's history notes |
| N9 | the earlier claim that the whole sequence ran on 3.11 and 3.12 at the verified commit was wrong (those runs were at 2d95681 with 50 tests). This round the full sequence really ran on 3.11.17, 3.12.15 and 3.13.5 (see results) |
| N10 | CONTRIBUTING.md now says to always build from a clean clone (ignored files such as old build/, dist/ or egg-info can leak into or distort artifacts) |
| N11 | `include requirements-dev.lock` added to MANIFEST.in; the sdist lists `requirements-dev.lock` (32 entries now) |

## Fifth round (pre-publication cleanups; CodeSentinel v5 findings N12, N13)
| Finding | Status |
|---|---|
| N13 lock package count said 14 | corrected: the lock pins 15 packages (15 `==` lines, checked with grep and by `pip list` in a fresh venv: 14 installed from the lock on Linux + pip, because `colorama` carries a Windows-only marker) |
| N12 README relative links did not resolve inside packages | the four relative links (`docs/decisions/0001-architecture.md`, `CONTRIBUTING.md` x2, `LICENSE`) are now plain text that says the file is in the source repository (LICENSE: also in sdist and wheel). No repository URL was invented. The packaged wheel README has 0 relative links (checked). `test_sample_markdown_matches_readme` still passes |
| twine check | ran `twine check` (twine 7.0.0, installed in a scratch venv outside the lock, so it is not pinned or hash-checked) on the 3.12 build: wheel PASSED, sdist PASSED. Local check only; nothing uploaded |

## Sixth round (N15: README links to the real repository)
| Item | Status |
|---|---|
| Remote state | (historical, at the time of the sixth round; superseded by the seventh round) `git remote -v`: origin = https://github.com/rodrix91/csv-quality-report.git; `git ls-remote` and `gh api` both gave `main` = `314fafce15aba859e75d8efb940b075fea4a6b5c` (it matched the local HEAD then); default branch `main`; `gh` authenticated as rodrix91 (read-only calls only) |
| N15 | the four plain-text mentions in README.md now link to https://github.com/rodrix91/csv-quality-report (repo root, `blob/main/docs/decisions/0001-architecture.md`, `blob/main/CONTRIBUTING.md` x2, `blob/main/LICENSE`). Each distinct URL returned HTTP 200 with `curl -sI`. The wheel's packaged README has no relative links. These links point at `main`; the commits of that round were later pushed (see the seventh round) |

## Seventh round (N18 stale statements; Dependabot rules)
| Item | Status |
|---|---|
| Real state | verified with git: `origin/main` = `1471ff4cd93a9948ab2b08640aaa9e6d67350442`; `HEAD` of `work/milestone-1` was `53197bfbfd2e6a5b3adcb8de9c540e93f3d89486`, an ancestor of it; `git merge --ff-only origin/main` fast-forwarded by one commit (`1471ff4`, adds `.github/dependabot.yml`, 12 lines). The 53197bf commits (README links, previous HANDOFF) are already on `origin/main`. Local `main` = `154e9ab`, an ancestor of `origin/main`, 33 commits behind |
| N18 | the statements "commits after 314fafce exist only locally / have NOT been pushed" and "local `main` is unrelated to `origin/main`" were false after the push and are removed; the statement that `main` holds only the scaffolding commit was corrected to the verified facts above |
| Other stale claims | "Tracked files 24" updated to 25; "HEAD changes only this file" re-stated against the new verified commit; the sixth-round remote-state row marked as historical. `.github/` holds only `dependabot.yml` (checked with `git ls-files .github`): there are no CI workflows, so "No CI" still holds |
| Scope | this revision changes only `HANDOFF.md` relative to `1471ff4c` |

## Dependabot updates
Verified from the repository: `.github/dependabot.yml` configures ecosystem `pip`, directory `/`, schedule weekly on Monday, at most 2 open PRs, label `dependencies`, commit-message prefix `deps`.

Not confirmed: that Dependabot really detects `requirements-dev.txt` (the only direct-dependency file), and whether its PRs also touch `requirements-dev.lock` or the `setuptools` pin in `pyproject.toml`. That stays unconfirmed until the first Dependabot PR exists; read each PR's file list instead of assuming. No CI workflow exists, so nothing automated runs the checks below; they are manual.

No Dependabot PR is merged unless all of this holds:
1. In a clean clone checked out at the PR branch, regenerate the hashed lock from `requirements-dev.txt` and commit it to the PR: `uv pip compile requirements-dev.txt --generate-hashes --universal --python-version 3.11 -o requirements-dev.lock` (command taken verbatim from CONTRIBUTING.md; run at `1471ff4c` with uv 0.12.22 it reproduced the committed lock exactly, `git diff` empty).
2. On Python 3.11, 3.12 and 3.13, each in a fresh venv: `pip install --require-hashes -r requirements-dev.lock`, then `python -m pytest -q`, `ruff check .`, `ruff format --check .` and `mypy`. If any step fails, the PR does not merge.
3. (B-3) If the PR changes the pinned `setuptools` in `[build-system]` of `pyproject.toml`, rebuild both artifacts with `python -m build` from a clean clone before merging, and check that the wheel and the sdist still contain `LICENSE`, byte-identical to the repository's file (`twine check` is a useful extra; twine is not in the lock, so use a scratch venv).

Baseline: steps 2 and 3 pass at `1471ff4c` on 3.11.17, 3.12.15 and 3.13.5 (see the results below).

## Verified commands for CodeSentinel
Run in a fresh `git clone` + fresh venv at the verified commit, installing ONLY from the lock (no `pip install -e .`; the package was confirmed not installed). All results are real. The full sequence below was run separately with Python 3.13.5, 3.11.17 and 3.12.15 (3.11 and 3.12 are uv-managed interpreters on this box; re-run again at the verified commit for this round, installs and builds hit PyPI only), each in its own fresh clone and venv, with identical results.

| Step | Command | Result |
|---|---|---|
| venv | `python3 -m venv .venv && . .venv/bin/activate` | ok |
| install | `pip install --require-hashes -r requirements-dev.lock` | ok on 3.11, 3.12 and 3.13; the lock pins 15 packages (verified: 15 `==` entries), of which 14 install on Linux (`colorama` is Windows-only) plus `pip` in the venv; no editable install |
| tests | `python -m pytest -q` | 54 passed, 0 failed on each of 3.11.17, 3.12.15, 3.13.5 (0.25 to 0.6s) |
| lint | `ruff check .` | All checks passed (ruff 0.16.10) |
| format | `ruff format --check .` | 16 files already formatted (ruff also checks Markdown code blocks, so the count dropped from 17 when LICENSE-PROPOSAL.md was removed; 12 of them are .py files) |
| types | `mypy` (strict; src and tests) | Success: no issues found in 12 source files (mypy 2.4.0) |
| build | `python -m build --wheel` | built csv_quality_report-0.1.0-py3-none-any.whl (downloads setuptools==84.0.0 from PyPI; that download is not hash-checked) |
| sdist | `python -m build --sdist`, then `tar tzf dist/*.tar.gz` | built csv_quality_report-0.1.0.tar.gz (32 entries); lists LICENSE, MANIFEST.in, requirements-dev.lock, tests/conftest.py, examples/sample.csv |
| sdist unpacked test | untar the sdist in a clean dir; new venv; `pip install --require-hashes -r requirements-dev.lock`; `python -m pytest -q` inside the unpacked dir (package not installed) | 54 passed on each of 3.11, 3.12, 3.13 |
| twine check | `twine check dist/*` (scratch venv, twine 7.0.0; not part of the lock) | PASSED for wheel and sdist on each of 3.11, 3.12, 3.13 |
| sdist vs MANIFEST.in | list the sdist and check expected entries | LICENSE, MANIFEST.in, requirements-dev.lock, tests/conftest.py, examples/sample.csv, examples/tiny.csv, README.md, pyproject.toml present; neither `HANDOFF.md` nor `.github/` is in the sdist (32 entries) |
| detect-secrets | `git ls-files -z \| xargs -0 detect-secrets scan` (detect-secrets 1.5.0 from CodeSentinel's venv, read-only use) | 0 findings |
| artifact license check | inspect wheel zip and sdist tar | wheel and sdist both contain LICENSE, byte-identical to the repo file; wheel metadata shows `License-Expression: MIT` and `License-File: LICENSE` |
| wheel smoke test | new clean venv, `pip install dist/*.whl`, then `csv-quality-report examples/tiny.csv --max-rows 1` and `python -m csv_quality_report examples/sample.csv` | both exit 0; sample output identical to the source run |
| README sample | `PYTHONPATH=src python3 -m csv_quality_report examples/sample.csv` | exit 0; output is contained verbatim in README.md (a test also enforces this) |
| secrets scan, tracked files | first command in the "Local secrets scan" block of CONTRIBUTING.md | no matches (exit 1) |
| secrets scan, history | second command in the same block (filters one known line, see history note) | no matches (exit 1) |

Earlier checks, not repeated at the verified commit: `pip install -r requirements-dev.txt` in a fresh venv gave a `pip freeze` identical to the old unhashed lock (before the lock was regenerated). The README-sample equivalence test (`test_sample_markdown_matches_readme`) exists and passed in every pytest run above, including from the unpacked sdist.

Scan pattern: AWS key ids, GitHub personal-token prefixes, PEM private-key headers, and key/secret/token/password names followed by a colon or equals sign. It is a plain grep, not a dedicated scanner.

not_run: coverage, pip-audit, CI workflow, Windows/macOS, large-file/performance tests. Known: the build-isolation download of setuptools==84.0.0 has no hash check (pinned by version only).

## Proposed GitHub description and topics (for GitRank)
Description: Quick data-quality report for a CSV file: types, missing values, distinct counts, top values and duplicate rows. Standard-library Python CLI (prototype/alpha).

Topics (8): `python`, `cli`, `csv`, `data-quality`, `data-profiling`, `data-analysis`, `standard-library`, `pytest`

## Capability summary (for GitAura)
1. `python -m csv_quality_report data.csv [--format markdown|json] [--max-rows N]` profiles a local UTF-8 CSV: per column inferred type (int/float/bool/date/string), missing count and %, distinct count, numeric min/max, top 3 values; plus the dataset's duplicate row count.
2. Fails clearly with distinct nonzero exit codes (3 unreadable, 4 not UTF-8, 5 empty, 6 ragged rows, 2 usage); duplicate column names get deterministic _2/_3 suffixes; unrepresentable numbers (huge integers, 1e999) degrade to string and JSON output is always standard JSON.
3. Python 3.11+, no runtime dependencies, 54 pytest tests; limitations: loads the whole file in memory (no streaming), heuristic type inference, UTF-8 only.

## Not verified / caveats
- Windows/macOS not tested. No CI workflows (only a Dependabot config exists). No large-file or performance testing. No coverage measurement.
- Network was used only to download dev tools and the build backend from PyPI; the tool itself makes no network calls.
- The hashed lock was generated with uv and verified with pip `--require-hashes`; the build-isolation setuptools download is pinned by version only.

## File manifest (24 tracked files, sha256, excluding this file)
```text
d7151503d304c8e41bba59f8b56b6c76d3931e46a70d46acf45c012c68ad67c5  .github/dependabot.yml
3e861aeb236be27a3b09a357ae458e64a5a31ab17733249981792cfaea96686d  .gitignore
ca0d6d67efde95cfe98a7b27bacd42597532d6e1ba67b788a4048471afc0d902  CONTRIBUTING.md
4af3d72e1de7c4168061f9059aa2a59c8226f90468069ce155ab3b1b8c861d72  LICENSE
aedd863cb18f2782f8202957fe0bc952c2d1a3bb67d4961f0f3b21c51b363be8  MANIFEST.in
4ffa29843efc74da370a43c502471d26c363969b0f6f2f7f2ffe6136809add28  README.md
df8e0eba971a01fa671e09cfaba25be563c7d3f044a03e919b2a39349fb8fbb0  docs/decisions/0001-architecture.md
765eb6bef0639221d201582e9da1148b38698a419cca29adf4d39fdf6423e9c4  examples/sample.csv
f1036be91dc016c6de3b52d42a3bb4f800ce6dbf9598e690c1ea4b95478ce2fd  examples/tiny.csv
9a8b3ee10e879dd4dc59a7667f67c6f6626237bccde8e2dece927c5ed4c2ac62  pyproject.toml
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
