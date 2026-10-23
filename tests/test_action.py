"""The GitHub Action's inputs and outputs are documented and reach its script (#138).

action.yml is read as text (the project has no YAML dependency): the keys of
the top-level ``inputs:`` and ``outputs:`` blocks are the lines indented by
exactly two spaces. The action itself runs end to end in the CI job ``action``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _block(name: str) -> str:
    """The text of a top-level block (``inputs:``) up to the next one."""
    match = re.search(rf"^{name}:\n(.*?)(?=^\S)", ACTION, re.M | re.S)
    assert match is not None, name
    return match[1]


def _keys(name: str) -> list[str]:
    return re.findall(r"^  ([a-z][a-z-]*):$", _block(name), re.M)


def _defaults() -> dict[str, str]:
    """Each input's default, without YAML quotes."""
    defaults: dict[str, str] = {}
    for chunk in re.split(r"^  (?=[a-z])", _block("inputs"), flags=re.M)[1:]:
        key = chunk.split(":", 1)[0]
        default = re.search(r"^    default: (.*)$", chunk, re.M)
        if default is not None:
            defaults[key] = default[1].strip().strip('"')
    return defaults


def _readme_rows(header: str) -> dict[str, list[str]]:
    """Rows of the README table that starts with ``header``, keyed by name."""
    table = README.split(header, 1)[1].split("\n\n", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in table.splitlines()[1:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        name = cells[0].strip("`")
        if name and not set(name) <= {"-"}:
            rows[name] = cells[1:]
    return rows


def test_parser_reads_the_action_file() -> None:
    assert _keys("inputs")[:2] == ["path", "args"]
    assert "baseline-used" in _keys("outputs")
    assert _defaults()["if-baseline-missing"] == "fail"
    assert _defaults()["args"] == ""


def test_readme_documents_every_input_with_its_default() -> None:
    rows = _readme_rows("| Input | Default | Meaning |")
    assert sorted(rows) == sorted(_keys("inputs"))
    defaults = _defaults()
    for name, cells in rows.items():
        documented = cells[0].strip("`").strip('"')
        if name in defaults:
            assert documented == defaults[name], name
        else:
            assert documented == "(required)", name


def test_readme_documents_every_output() -> None:
    assert sorted(_readme_rows("| Output | Meaning |")) == sorted(_keys("outputs"))


def test_every_input_reaches_the_script() -> None:
    """Each input is used, and only through an environment variable."""
    run = ACTION.split("    - name: Run csv-quality-report\n", 1)[1]
    script = run.split("      run: |\n", 1)[1]
    for name in _keys("inputs"):
        if name == "python-version":  # used by actions/setup-python
            continue
        variable = "INPUT_" + name.upper().replace("-", "_")
        assert f"        {variable}: ${{{{ inputs.{name} }}}}\n" in run, name
        assert f"${variable}" in script or f"${{{variable}" in script, name
    assert "${{" not in script


def test_every_output_is_written() -> None:
    script = ACTION.split("      run: |\n")[-1]
    for name in _keys("outputs"):
        assert f"steps.run.outputs.{name} }}}}" in _block("outputs"), name
        assert f'echo "{name}=' in script, name


def _released_versions() -> list[tuple[int, ...]]:
    """Versions with a dated CHANGELOG section, newest first."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    found = re.findall(r"^## \[(\d+)\.(\d+)\.(\d+)\] - \d{4}-\d{2}-\d{2}$", changelog, re.M)
    return [tuple(map(int, version)) for version in found]


def test_readme_pins_a_recent_release() -> None:
    # The README examples use inputs and options of the newest releases (the
    # daily workflow needs `baseline` from 0.20.0 and `--min-rows` from
    # 0.21.0), so a pin left behind documents a workflow that fails. The pin
    # follows a release once its tag exists: it may name the newest dated
    # section or, while that version waits for its tag, the one before it.
    pins = re.findall(r"rodrix91/csv-quality-report@v(\d+)\.(\d+)\.(\d+)\b", README)
    assert pins, "no pinned Action example in the README"
    assert len(set(pins)) == 1, f"the README examples pin different tags: {sorted(set(pins))}"
    released = _released_versions()
    assert len(released) >= 2 and released == sorted(released, reverse=True)
    assert tuple(map(int, pins[0])) in released[:2], (
        f"the README pins v{'.'.join(pins[0])}; pin the latest release tag"
    )
