"""The GitHub Action's ``options-file`` input (issue #325)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from csv_quality_report.optionsfile import OptionsFileError
from scripts.validate_action_options_file import (
    HELP_VERSION,
    main,
    reserved_reason,
    validate_options_file,
)
from scripts.validate_action_read_path import validate_read_path

ROOT = Path(__file__).resolve().parent.parent
ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")
DATA = (
    "Nro de guía;Estado;Fecha entrega\n"
    "G-1;Entregado;05/11/2026\n"
    "G-2;En tránsito;\n"
    "G-3;Entregado;06/11/2026\n"
)
OPTIONS = (
    "# courier export\n"
    "--delimiter auto --date-order dmy\n"
    '--unique "Nro de guía"\n'
    "--require-when 'Fecha entrega' Estado=Entregado\n"
)


def write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8", newline="")
    else:
        path.write_bytes(content)
    return path


# --- the guard -----------------------------------------------------------------------


@pytest.mark.parametrize("token", sorted(HELP_VERSION))
def test_help_and_version_are_refused(token: str) -> None:
    assert reserved_reason(token) == "help/version options are not supported in the Action"


@pytest.mark.parametrize(
    "token", ["--baseline", "--ba", "--baseline=x.json", "--json-output", "--j=x.json", "--json"]
)
def test_reserved_inputs_are_refused(token: str) -> None:
    reason = reserved_reason(token)
    assert reason is not None and "--baseline and --json-output are reserved" in reason


@pytest.mark.parametrize(
    "token", ["--unique", "Nro de guía", "--help-me", "--b", "-", "", "--format", "baseline"]
)
def test_other_tokens_pass(token: str) -> None:
    assert reserved_reason(token) is None


def test_the_guard_matches_the_args_guard_of_action_yml() -> None:
    # The same help/version tokens and prefixes as the case statement for args.
    guard = ACTION.split('for token in "${extra[@]}" "${baseline_extra[@]}"; do', 1)[1]
    guard = guard.split("        done", 1)[0]
    help_line = next(line for line in guard.splitlines() if "--help" in line)
    assert set(help_line.strip().rstrip(")").split(" | ")) == HELP_VERSION
    assert "--ba* | --j*)" in guard


# --- validating and copying a file ---------------------------------------------------


def test_valid_file_is_copied_byte_for_byte(tmp_path: Path) -> None:
    source = write(tmp_path / "checks.opts", b"\xef\xbb\xbf" + OPTIONS.encode() + b"\r\n")
    copy = tmp_path / "copy.opts"
    assert validate_options_file(str(source), str(copy))[-3:] == [
        "--require-when",
        "Fecha entrega",
        "Estado=Entregado",
    ]
    assert copy.read_bytes() == source.read_bytes()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("--top 3\n--json-output=x.json\n", "line 2: --json-output=x.json: use the Action"),
        ("--top 3\n\n--baseline old.json\n", "line 3: --baseline: use the Action"),
        ("--help\n", "line 1: --help: help/version options are not supported in the Action"),
        ("--unique a --vers\n", "line 1: --vers: help/version"),
    ],
)
def test_reserved_options_are_refused_with_their_line(
    tmp_path: Path, content: str, message: str
) -> None:
    source = write(tmp_path / "checks.opts", content)
    copy = tmp_path / "copy.opts"
    with pytest.raises(ValueError, match="options-file '.*checks.opts': ") as excinfo:
        validate_options_file(str(source), str(copy))
    assert message in str(excinfo.value)
    assert not copy.exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("--opt other.opts\n", "line 1: an options file cannot include another one (--opt)"),
        ('--unique "a\n', 'line 1: unclosed " quote'),
        ("--top 3\n-- x\n", "line 2: a bare --"),
        (b"--na N\xba\n", "line 1: not valid UTF-8 (byte 0xBA)"),
    ],
)
def test_parse_errors_are_the_cli_ones(tmp_path: Path, content: str | bytes, message: str) -> None:
    source = write(tmp_path / "checks.opts", content)
    with pytest.raises(OptionsFileError, match="^--options-file ") as excinfo:
        validate_options_file(str(source), str(tmp_path / "copy.opts"))
    assert message in str(excinfo.value)


def test_main(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    good = write(tmp_path / "good.opts", "--top 3\n")
    bad = write(tmp_path / "bad.opts", "--json-output x.json\n")
    copy = tmp_path / "copy.opts"
    monkeypatch.setattr(sys, "argv", ["v", str(good), str(copy)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["v", str(bad), str(copy)])
    assert main() == 2
    monkeypatch.setattr(sys, "argv", ["v", str(tmp_path / "missing.opts"), str(copy)])
    assert main() == 2
    monkeypatch.setattr(sys, "argv", ["v", str(good), str(tmp_path / "no" / "dir" / "c.opts")])
    assert main() == 2
    monkeypatch.setattr(sys, "argv", ["v"])
    assert main() == 2
    err = capsys.readouterr().err.splitlines()
    assert err[0].endswith(
        "line 1: --json-output: use the Action baseline/report-path inputs; "
        "--baseline and --json-output are reserved"
    )
    assert "cannot read it: " in err[1]
    assert "No such file or directory" in err[2]
    assert err[3].startswith("usage: ")


def test_read_path_validator_knows_the_options_file_kind(tmp_path: Path) -> None:
    write(tmp_path / "checks.opts", "--top 3\n")
    validate_read_path("checks.opts", str(tmp_path), "options-file")
    with pytest.raises(ValueError, match="^options-file must stay within GITHUB_WORKSPACE$"):
        validate_read_path("../checks.opts", str(tmp_path), "options-file")
    with pytest.raises(ValueError, match="^options-file must be relative"):
        validate_read_path(str(tmp_path / "checks.opts"), str(tmp_path), "options-file")
    with pytest.raises(ValueError, match="path, baseline or options-file"):
        validate_read_path("checks.opts", str(tmp_path), "other")


# --- the Action's script, end to end -------------------------------------------------


def run_action(tmp_path: Path, **inputs: str) -> tuple[int, dict[str, str], str]:
    """Run the Action's run script with Bash, as the runner would."""
    script = ACTION.split("    - name: Run csv-quality-report\n", 1)[1].split("      run: |\n", 1)[
        1
    ]
    script = "\n".join(line[8:] for line in script.splitlines())
    workspace = tmp_path / "workspace"
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    output = tmp_path / "github-output"
    output.touch()
    env = {
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), "/usr/bin", "/bin"]),
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
        "ACTION_PATH": str(ROOT),
        "GITHUB_WORKSPACE": str(workspace),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_ACTION": "check",
        "RUNNER_TEMP": str(temp),
        "INPUT_SUMMARY": "false",
        "INPUT_IF_BASELINE_MISSING": "fail",
    }
    for name in ("path", "args", "options-file", "report-path", "baseline", "baseline-args"):
        env["INPUT_" + name.upper().replace("-", "_")] = inputs.get(name.replace("-", "_"), "")
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    outputs = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if line
    )
    return result.returncode, outputs, result.stdout + result.stderr


needs_bash = pytest.mark.skipif(sys.platform == "win32", reason="the Action runs with Bash")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    write(tmp_path / "workspace" / "data" / "envios.csv", DATA)
    write(tmp_path / "workspace" / "checks" / "envios.opts", OPTIONS)
    return tmp_path / "workspace"


@needs_bash
def test_action_reads_column_names_with_spaces_from_the_file(
    tmp_path: Path, workspace: Path
) -> None:
    code, outputs, log = run_action(
        tmp_path,
        path="data/envios.csv",
        options_file="checks/envios.opts",
        report_path="reports/envios.json",
    )
    assert code == 0, log
    assert outputs["passed"] == "true"
    report = json.loads((workspace / "reports" / "envios.json").read_text(encoding="utf-8"))
    assert [(c["check"], c["column"], c["passed"]) for c in report["checks"]] == [
        ("unique", "Nro de guía", True),
        ("required_when", "Fecha entrega", True),
    ]


@needs_bash
def test_args_come_after_the_file(tmp_path: Path, workspace: Path) -> None:
    write(workspace / "checks" / "top.opts", "--top 3\n")
    code, _, log = run_action(
        tmp_path,
        path="data/envios.csv",
        options_file="checks/top.opts",
        args="--delimiter ; --top 1",
        report_path="reports/top.json",
    )
    assert code == 0, log
    report = json.loads((workspace / "reports" / "top.json").read_text(encoding="utf-8"))
    assert all(len(column["top_values"]) == 1 for column in report["columns"])


@needs_bash
def test_a_failed_gate_from_the_file_fails_the_action(tmp_path: Path, workspace: Path) -> None:
    write(workspace / "checks" / "strict.opts", "--delimiter ';'\n--require-columns 'Peso kg'\n")
    code, outputs, log = run_action(
        tmp_path, path="data/envios.csv", options_file="checks/strict.opts"
    )
    assert code == 8, log
    assert outputs["passed"] == "false"
    assert "required column 'Peso kg' is missing" in log


@needs_bash
@pytest.mark.parametrize(
    ("options_file", "content", "message"),
    [
        ("checks/x.opts", "--json-output=../../stolen.json\n", "line 1: --json-output="),
        ("checks/x.opts", "--delimiter ';'\n--help\n", "line 2: --help: help/version"),
        ("checks/x.opts", "--baseline=old.json\n", "line 1: --baseline=old.json"),
        ("checks/x.opts", "--o other.opts\n", "cannot include another one (--o)"),
        ("checks/missing.opts", None, "cannot read it: "),
        ("../outside.opts", "--top 3\n", "options-file must stay within GITHUB_WORKSPACE"),
    ],
)
def test_action_refuses_bad_files_before_any_report(
    tmp_path: Path, workspace: Path, options_file: str, content: str | None, message: str
) -> None:
    if content is not None:
        write(workspace / options_file, content)
    code, outputs, log = run_action(
        tmp_path,
        path="data/envios.csv",
        options_file=options_file,
        report_path="reports/bad.json",
    )
    assert (code, outputs["passed"], outputs["report-json"]) == (2, "false", ""), log
    assert message in log
    assert not (workspace / "reports").exists()
    assert not (tmp_path / "stolen.json").exists()


@needs_bash
def test_args_still_refuse_options_file(tmp_path: Path, workspace: Path) -> None:
    code, _, log = run_action(
        tmp_path, path="data/envios.csv", args="--options-file checks/envios.opts"
    )
    assert code == 2
    assert "--options-file is not supported in Action args; use the options-file input" in log
