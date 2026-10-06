# Contributing

Project status: prototype/alpha, maintained by rodrix91. Small, focused changes with tests are welcome.

## Setup

Requires Python 3.11+. From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock   # exact pins + hashes (or: pip install -r requirements-dev.txt)
pip install -e .                      # optional: only for the `csv-quality-report` command
```

The tests do not need `pip install -e .` (pytest puts `src/` on the path and subprocess tests set `PYTHONPATH=src`). Run all commands from the repository root.

## Checks (run all before opening a PR)

```bash
python -m pytest                 # tests
coverage run -m pytest && coverage combine && coverage report   # tests + 100% line/branch coverage (CI enforces it)
ruff check .                     # lint
ruff format --check .            # formatting (run `ruff format .` to fix)
mypy                             # strict type check (config in pyproject.toml)
python -m build                  # build sdist + wheel into dist/ (needs network to fetch setuptools)
```

**Always build from a clean clone** (`git clone <repo> /tmp/build-check && cd /tmp/build-check`), not from a working directory that has stray files: the sdist and wheel are assembled from whatever is on disk, and files that are ignored by git (old `build/`, `dist/`, `*.egg-info`, local notes) can leak into or distort the artifacts.

The test suite must also pass from the unpacked sdist: CI builds it and runs the tests there (job `sdist`). When a test starts reading a new file outside `src/` and `tests/test_*.py` (data, a script), add it to `MANIFEST.in`.

If a change alters the output, refresh the samples embedded in the README with `python scripts/update_readme_samples.py` and the outputs in `docs/guides/spanish-exports.md` with `python scripts/update_guide.py` (`--check` only reports, for both); the test suite fails while they are stale.

The end-to-end corpus in `tests/corpus` (realistic files with their options) has expected JSON reports too. After an intended change, run `python scripts/update_corpus.py` and review the diff of `tests/corpus/expected/`; that diff is the change in behavior. See `tests/corpus/README.md`.

Quick manual check of the CLI (prefix with `PYTHONPATH=src` if the package is not installed):

```bash
python -m csv_quality_report examples/sample.csv
python -m csv_quality_report examples/tiny.csv --format json
```

Local secrets scan (tracked files and git history; exit code 1 / no output means no matches):

```bash
git grep -EIn "(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret|token|passw(or)?d)[\"' ]*[:=])"
git log -p --all | grep -EIn "(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret|token|passw(or)?d)[\"' ]*[:=])" | grep -vF 'positive control with a fake'
```

The history scan filters out exactly one known false positive: a line in a stale `HANDOFF.md` revision (commit `c960391`, committed by accident, and its later removal) that described the scan's own test file. It was inspected and is not a secret. Everything else in history, including the rest of `HANDOFF.md`, is scanned.

This is a simple pattern check, not a substitute for a dedicated scanner.

## Guidelines

- Runtime code must stay standard-library only. Dev tools go in `requirements-dev.txt`. After changing them, regenerate the hashed lock with [uv](https://docs.astral.sh/uv/) (the lock was generated with uv 0.12.22): `uv pip compile requirements-dev.txt --generate-hashes --universal --python-version 3.11 -o requirements-dev.lock`.
- The build backend is pinned exactly in `pyproject.toml` (`setuptools==84.0.0`); `python -m build` downloads it in an isolated environment, and that download is not covered by `requirements-dev.lock` hashes.
- Add or update behavior tests in `tests/` for every behavior change.
- If you change the CLI output, regenerate the samples in `README.md` with `python scripts/update_readme_samples.py`; the README tests in `tests/test_cli.py` fail when they drift.
- Keep type hints on all functions; keep modules small.
- Use small commits with honest messages.

## Dependency updates (Dependabot)

Dependabot opens weekly PRs for the pinned dev tools. These rules were first recorded in `HANDOFF.md` (kept as a historical record) and are maintained here. It edits `requirements-dev.txt` but may not regenerate the hashed lock, so do not merge a Dependabot PR as is:

1. In a clean clone of the PR branch, regenerate `requirements-dev.lock` with the `uv pip compile` command above and push it to the PR.
2. CI must pass on Python 3.11, 3.12 and 3.13 with `pip install --require-hashes -r requirements-dev.lock` (tests with 100% coverage, Ruff, strict mypy).
3. If the PR changes the `setuptools` pin in `pyproject.toml`, rebuild from a clean clone and check that the wheel and the sdist still contain `LICENSE`.

## License

By contributing you agree that your contribution is licensed under the MIT License (see `LICENSE`).
