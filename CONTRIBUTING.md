# Contributing

Project status: prototype/alpha, maintained by rodrix91. Small, focused changes with tests are welcome.

## Setup

Requires Python 3.11+. From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt   # or: pip install -r requirements-dev.lock  (exact pins)
pip install -e .
```

## Checks (run all before opening a PR)

```bash
python -m pytest                 # tests
ruff check .                     # lint
ruff format --check .            # formatting (run `ruff format .` to fix)
mypy                             # strict type check (config in pyproject.toml)
python -m build --wheel          # build wheel into dist/ (needs network to fetch setuptools)
```

Quick manual check of the CLI:

```bash
python -m csv_quality_report examples/sample.csv
python -m csv_quality_report examples/tiny.csv --format json
```

Local secrets scan (tracked files; no output and exit code 1 from `grep` means no matches):

```bash
git ls-files -z | xargs -0 grep -EIn "(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret|token|passw(or)?d)[\"' ]*[:=])"
```

## Guidelines

- Runtime code must stay standard-library only. Dev tools go in `requirements-dev.txt`; refresh `requirements-dev.lock` with `pip freeze --exclude-editable > requirements-dev.lock` after changing them.
- Add or update behavior tests in `tests/` for every behavior change.
- If you change the CLI output, regenerate the sample output in `README.md`; `tests/test_cli.py::test_sample_markdown_matches_readme` fails when they drift.
- Keep type hints on all functions; keep modules small.
- Use small commits with honest messages.

## License

License: pending owner decision (see `LICENSE-PROPOSAL.md`).
