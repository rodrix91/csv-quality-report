"""Tests for ``--options-file FILE`` (issue #323)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report.cli import _options_file_matcher, build_parser, main
from csv_quality_report.optionsfile import (
    MAX_OPTIONS_FILE_BYTES,
    OptionsFileError,
    parse_options_text,
    read_options_file,
    split_options_line,
)

WriteCsv = Callable[..., Path]
ROOT = Path(__file__).resolve().parent.parent
# A courier export with Spanish column names that contain spaces.
DATA = (
    "Nro de guía;Estado;Fecha entrega;Peso kg\n"
    "G-1;Entregado;05/11/2026;1,5\n"
    "G-2;En tránsito;;2,25\n"
    "G-3;Entregado;;s/d\n"
    "G-3;Devuelto;07/11/2026;3\n"
)
OPTIONS = (
    "# Reading options of the courier export\n"
    "--delimiter ';' --decimal-comma --na s/d\n"
    "--date-order dmy\n"
    "\n"
    "    # gates\n"
    '--unique "Nro de guía"\n'
    "--require-when 'Fecha entrega' Estado=Entregado\n"
)


def never(token: str) -> bool:
    return False


def write_options(tmp_path: Path, text: str | bytes, name: str = "checks.opts") -> Path:
    path = tmp_path / name
    if isinstance(text, str):
        path.write_text(text, encoding="utf-8", newline="")
    else:
        path.write_bytes(text)
    return path


def run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        code = main(argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


def checks_of(out: str) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = json.loads(out)["checks"]
    return checks


# --- splitting a line -----------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "tokens"),
    [
        ("", []),
        ("   \t ", []),
        ("--max-missing 5 --max-duplicates 0", ["--max-missing", "5", "--max-duplicates", "0"]),
        ("--max-missing\t5", ["--max-missing", "5"]),
        ("  --top   3  ", ["--top", "3"]),
        ('--unique "Nro de guía"', ["--unique", "Nro de guía"]),
        ("--unique 'Nro de guía'", ["--unique", "Nro de guía"]),
        # A quoted part joins the text next to it, as in a shell.
        ('--na="s/d,sin dato"', ["--na=s/d,sin dato"]),
        ('"Fecha "entrega', ["Fecha entrega"]),
        # The other kind of quote is literal inside quotes.
        ('--unique "O\'Higgins"', ["--unique", "O'Higgins"]),
        ("--allowed-values 'Nota=\"A\",B'", ["--allowed-values", 'Nota="A",B']),
        # An empty pair of quotes is an empty token.
        ('--na ""', ["--na", ""]),
        ("''", [""]),
        # Backslashes are literal: regular expressions and Windows paths.
        (r"--pattern CUIT=\d{2}-\d{8}-\d", ["--pattern", r"CUIT=\d{2}-\d{8}-\d"]),
        (r"--baseline C:\reportes\ayer.json", ["--baseline", r"C:\reportes\ayer.json"]),
        # No inline comments: # inside a line is text.
        ("--na #N/A,s/d", ["--na", "#N/A,s/d"]),
        ("--top 3 # three", ["--top", "3", "#", "three"]),
        # A no-break space is part of a name, not a separator.
        ("--unique Nro\u00a0guía", ["--unique", "Nro\u00a0guía"]),
    ],
)
def test_split_options_line(line: str, tokens: list[str]) -> None:
    assert split_options_line(line) == tokens


@pytest.mark.parametrize(("line", "quote"), [('--unique "Nro de guía', '"'), ("--na 's/d", "'")])
def test_unclosed_quote(line: str, quote: str) -> None:
    with pytest.raises(ValueError, match=f"^unclosed {quote} quote$"):
        split_options_line(line)


# --- parsing a file's text --------------------------------------------------------


def test_parse_keeps_line_numbers_and_skips_comments() -> None:
    assert parse_options_text(OPTIONS) == [
        (2, "--delimiter"),
        (2, ";"),
        (2, "--decimal-comma"),
        (2, "--na"),
        (2, "s/d"),
        (3, "--date-order"),
        (3, "dmy"),
        (6, "--unique"),
        (6, "Nro de guía"),
        (7, "--require-when"),
        (7, "Fecha entrega"),
        (7, "Estado=Entregado"),
    ]


def test_parse_accepts_crlf_and_a_missing_final_newline() -> None:
    assert parse_options_text("--top 3\r\n# c\r\n\t# c\r\n--max-rows 2") == [
        (1, "--top"),
        (1, "3"),
        (4, "--max-rows"),
        (4, "2"),
    ]


def test_a_quoted_hash_at_the_start_is_not_a_comment() -> None:
    assert parse_options_text("'#N/A'") == [(1, "#N/A")]


@pytest.mark.parametrize("char", ["\x00", "\x07", "\x1b", "\r", "\x0b", "\x7f", "\x85", "\x9f"])
def test_control_characters_are_refused_with_their_line(char: str) -> None:
    with pytest.raises(ValueError, match=rf"^line 2: control character U\+{ord(char):04X} "):
        parse_options_text(f"--top 3\n--na s/d{char}x\n")


def test_unclosed_quote_names_its_line() -> None:
    with pytest.raises(ValueError, match='^line 3: unclosed " quote$'):
        parse_options_text('--top 3\n\n--unique "Nro\n')


# --- reading a file -----------------------------------------------------------------


def test_read_options_file(tmp_path: Path) -> None:
    path = write_options(tmp_path, OPTIONS)
    assert read_options_file(str(path), is_options_file=never)[-3:] == [
        "--require-when",
        "Fecha entrega",
        "Estado=Entregado",
    ]


def test_a_utf8_bom_is_removed(tmp_path: Path) -> None:
    path = write_options(tmp_path, b"\xef\xbb\xbf--unique Gu\xc3\xada\n")
    assert read_options_file(str(path), is_options_file=never) == ["--unique", "Guía"]


def test_only_one_bom_is_removed(tmp_path: Path) -> None:
    # A second BOM is text: it is part of the token, as a stray U+FEFF would be.
    path = write_options(tmp_path, b"\xef\xbb\xbf\xef\xbb\xbf--top 3\n")
    assert read_options_file(str(path), is_options_file=never) == ["\ufeff--top", "3"]


def test_an_empty_file_has_no_options(tmp_path: Path) -> None:
    assert read_options_file(str(write_options(tmp_path, "")), is_options_file=never) == []


def test_not_utf8_names_the_line_and_byte(tmp_path: Path) -> None:
    # cp1252 'í' on line 3.
    path = write_options(tmp_path, b"# ok\n--top 3\n--unique Gu\xeda\n")
    with pytest.raises(OptionsFileError) as excinfo:
        read_options_file(str(path), is_options_file=never)
    assert str(excinfo.value) == (
        f"--options-file '{path}': line 3: not valid UTF-8 (byte 0xED); save the file as UTF-8"
    )


def test_not_utf8_line_counts_after_the_bom(tmp_path: Path) -> None:
    path = write_options(tmp_path, b"\xef\xbb\xbf\xff\n")
    with pytest.raises(OptionsFileError, match=r": line 1: not valid UTF-8 \(byte 0xFF\)"):
        read_options_file(str(path), is_options_file=never)


def test_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "nope.opts"
    with pytest.raises(OptionsFileError, match=r"^--options-file '.*nope\.opts': cannot read it: "):
        read_options_file(str(path), is_options_file=never)


def test_directory(tmp_path: Path) -> None:
    with pytest.raises(OptionsFileError, match="cannot read it: "):
        read_options_file(str(tmp_path), is_options_file=never)


def test_standard_input_is_reserved_for_the_csv() -> None:
    with pytest.raises(OptionsFileError, match="standard input is reserved for the CSV"):
        read_options_file("-", is_options_file=never)


def test_size_limit(tmp_path: Path) -> None:
    filler = b"# " + b"x" * (MAX_OPTIONS_FILE_BYTES - 11) + b"\n--top 3\n"
    assert len(filler) == MAX_OPTIONS_FILE_BYTES
    at_limit = write_options(tmp_path, filler)
    assert read_options_file(str(at_limit), is_options_file=never) == ["--top", "3"]
    over = write_options(tmp_path, b" " + filler, "big.opts")
    with pytest.raises(OptionsFileError, match="larger than 1 MiB.*CSV file passed by mistake"):
        read_options_file(str(over), is_options_file=never)


def test_a_bare_double_dash_is_refused(tmp_path: Path) -> None:
    path = write_options(tmp_path, "--top 3\n-- data.csv\n")
    with pytest.raises(OptionsFileError, match="line 2: a bare -- cannot be used"):
        read_options_file(str(path), is_options_file=never)


def test_a_quoted_double_dash_is_refused_too(tmp_path: Path) -> None:
    # argparse cannot tell the quotes apart: the token is still "--".
    path = write_options(tmp_path, "'--'\n")
    with pytest.raises(OptionsFileError, match="line 1: a bare --"):
        read_options_file(str(path), is_options_file=never)


# --- recognising the option the way argparse does ---------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("--options-file", True),
        ("--options-file=x.opts", True),
        ("--o", True),
        ("--opt", True),
        ("--options-fil=x", True),
        ("--options-files", False),
        ("--option-file", False),
        ("--", False),
        ("-", False),
        ("", False),
        ("--=x", False),
        ("-o", False),
        ("options-file", False),
        ("x.opts", False),
        ("--max-rows", False),
    ],
)
def test_options_file_matcher(token: str, expected: bool) -> None:
    assert _options_file_matcher(build_parser())(token) is expected


def test_an_ambiguous_prefix_is_left_to_argparse() -> None:
    parser = build_parser()
    parser.add_argument("--options-extra")
    matches = _options_file_matcher(parser)
    assert matches("--options-f")
    assert not matches("--options")
    assert not matches("--o")


def test_no_abbreviations_when_argparse_allows_none() -> None:
    parser = build_parser()
    parser.allow_abbrev = False
    matches = _options_file_matcher(parser)
    assert matches("--options-file=x")
    assert not matches("--opt")


def test_no_other_option_starts_with_the_prefix_the_action_refuses() -> None:
    # The Action refuses every token starting with --o (action.yml); that is
    # only exact while --options-file is the only option starting with --o.
    options = [o for o in build_parser()._option_string_actions if o.startswith("--o")]
    assert options == ["--options-file"]


# --- the command line ---------------------------------------------------------------


def test_file_gives_the_same_report_as_the_command_line(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv = str(write_csv(DATA))
    opts = str(write_options(tmp_path, OPTIONS))
    direct = [
        "--delimiter",
        ";",
        "--decimal-comma",
        "--na",
        "s/d",
        "--date-order",
        "dmy",
        "--unique",
        "Nro de guía",
        "--require-when",
        "Fecha entrega",
        "Estado=Entregado",
    ]
    code, out, err = run([csv, "--format", "json", *direct], capsys)
    assert code == 8
    assert run([csv, "--format", "json", "--options-file", opts], capsys) == (code, out, err)
    assert [(c["check"], c["column"], c["passed"]) for c in checks_of(out)] == [
        ("unique", "Nro de guía", False),
        ("required_when", "Fecha entrega", False),
    ]
    # The file may also come first, before the path.
    assert run(["--options-file", opts, csv, "--format", "json"], capsys) == (code, out, err)


@pytest.mark.parametrize(
    "form",
    [
        ["--options-file", "{}"],
        ["--options-file={}"],
        ["--opt", "{}"],
        ["--o={}"],
    ],
)
def test_long_form_attached_value_and_abbreviations(
    form: list[str], write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv = str(write_csv("a,b\n1,x\n1,y\n"))
    opts = str(write_options(tmp_path, "--unique a\n"))
    code, out, _ = run([csv, "--format", "json", *(t.format(opts) for t in form)], capsys)
    assert code == 8
    assert [c["check"] for c in checks_of(out)] == ["unique"]


def test_options_are_inserted_in_place(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv = str(write_csv("a\n1\n2\n2\n3\n"))
    opts = str(write_options(tmp_path, "--top 3\n"))
    later = json.loads(
        run([csv, "--format", "json", "--options-file", opts, "--top", "1"], capsys)[1]
    )
    earlier = json.loads(
        run([csv, "--format", "json", "--top", "1", "--options-file", opts], capsys)[1]
    )
    assert len(later["columns"][0]["top_values"]) == 1  # the command line wins
    assert len(earlier["columns"][0]["top_values"]) == 3  # the file wins


def test_repeatable_options_add_up_across_files(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv = str(write_csv("a,b,c\n1,x,p\n2,x,p\n"))
    one = str(write_options(tmp_path, "--unique a\n", "one.opts"))
    two = str(write_options(tmp_path, "--unique b\n", "two.opts"))
    argv = [csv, "--format", "json", "--options-file", one, "--options-file", two, "--unique", "c"]
    code, out, _ = run(argv, capsys)
    assert code == 8
    assert [(c["column"], c["passed"]) for c in checks_of(out)] == [
        ("a", True),
        ("b", False),
        ("c", False),
    ]


def test_an_empty_file_changes_nothing(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv = str(write_csv("a\n1\n"))
    opts = str(write_options(tmp_path, "# nothing yet\n"))
    plain = run([csv, "--format", "json"], capsys)
    assert run([csv, "--format", "json", "--options-file", opts], capsys) == plain


def test_options_after_a_double_dash_are_not_expanded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # After --, argparse reads "--options-file" as the CSV path.
    monkeypatch.chdir(tmp_path)
    code, out, err = run(["--", "--options-file"], capsys)
    assert (code, out) == (3, "")
    assert "cannot read '--options-file'" in err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--options-file"], "argument --options-file: expected one argument"),
        (["--options-file", "--top", "3"], "argument --options-file: expected one argument"),
        (["--opt"], "argument --options-file: expected one argument"),
        (["--options-file", "-"], "standard input is reserved for the CSV"),
        (["--options-file", "missing.opts"], "--options-file 'missing.opts': cannot read it: "),
    ],
)
def test_usage_errors(
    argv: list[str],
    message: str,
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv = str(write_csv("a\n1\n"))
    monkeypatch.chdir(tmp_path)
    code, out, err = run([csv, *argv], capsys)
    assert (code, out) == (2, "")
    assert message in err


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("--top 3\n--options-file other.opts\n", "line 2: an options file cannot include another"),
        ("--o=other.opts\n", "line 1: an options file cannot include another one (--o)"),
        ('--top 3\n\n--unique "a\n', 'line 3: unclosed " quote'),
        ("--top 3\n-- x.csv\n", "line 2: a bare -- cannot be used"),
        ("--top\x1b[2J 3\n", "line 1: control character U+001B"),
        (b"--na s/d\n--na N\xba\n", "line 2: not valid UTF-8 (byte 0xBA)"),
    ],
)
def test_file_errors_are_usage_errors_with_the_file_and_line(
    content: str | bytes,
    message: str,
    write_csv: WriteCsv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    csv = str(write_csv("a\n1\n"))
    opts = write_options(tmp_path, content)
    code, out, err = run([csv, "--options-file", str(opts)], capsys)
    assert (code, out) == (2, "")
    assert f"error: --options-file '{opts}': {message}" in err


def test_file_options_are_validated_like_command_line_ones(
    write_csv: WriteCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv = str(write_csv("a\n1\n"))
    opts = str(write_options(tmp_path, "--max-rows 0\n"))
    code, _, err = run([csv, "--options-file", opts], capsys)
    assert code == 2
    assert "--max-rows" in err


def test_subprocess_run_reads_sys_argv(
    write_csv: WriteCsv, tmp_path: Path, cli_env: dict[str, str]
) -> None:
    csv = str(write_csv(DATA))
    opts = str(write_options(tmp_path, OPTIONS))
    result = subprocess.run(
        [sys.executable, "-m", "csv_quality_report", csv, "--options-file", opts],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=cli_env,
        check=False,
    )
    assert result.returncode == 8
    assert "check failed: column 'Nro de guía' is not unique" in result.stderr
    assert "check failed: column 'Fecha entrega' is missing in 1 of 2 rows" in result.stderr


# --- the GitHub Action refuses the option -------------------------------------------


def _action_guard() -> str:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    script = action.split("      run: |\n", 1)[1]
    loop = 'for token in "${extra[@]}" "${baseline_extra[@]}"; do'
    body = script.split(loop, 1)[1].split("        done", 1)[0]
    return f"{loop}{body}done\n"


@pytest.mark.skipif(sys.platform == "win32", reason="the Action runs its script with Bash")
@pytest.mark.parametrize(
    ("args", "baseline_args", "code"),
    [
        ("--max-rows 1 --unique a", "", 0),
        ("--options-file checks.opts", "", 2),
        ("--options-file=checks.opts", "", 2),
        ("--max-rows 1 --opt checks.opts", "", 2),
        ("--o=checks.opts", "", 2),
        ("", "--options-file checks.opts", 2),
        ("", "--max-row-drop 50", 0),
    ],
)
def test_action_refuses_options_files(args: str, baseline_args: str, code: int) -> None:
    script = (
        'annotate() { printf "%s\\n" "$2"; }\n'
        'finish() { exit "$1"; }\n'
        "set -f\n"
        'read -r -a extra <<< "$INPUT_ARGS"\n'
        'read -r -a baseline_extra <<< "$INPUT_BASELINE_ARGS"\n'
        "set +f\n" + _action_guard()
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"INPUT_ARGS": args, "INPUT_BASELINE_ARGS": baseline_args, "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert result.returncode == code, result.stdout
    if code:
        assert "--options-file is not supported in Action args" in result.stdout


# --- the README example -------------------------------------------------------------


def test_readme_example_file_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("### Options files\n", 1)[1]
    example = section.split("```text\n", 1)[1].split("```", 1)[0]
    command = section.split("```sh\n", 1)[1].split("```", 1)[0].split()
    assert command[:3] == ["python", "-m", "csv_quality_report"]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "checks").mkdir()
    write_options(tmp_path, example, "checks/envios.opts")
    (tmp_path / "envios.csv").write_text(
        "Nro de guía;Estado;Fecha entrega;Peso kg\n"
        "G-1;Entregado;05/11/2026;1.234,5\n"
        "G-2;En tránsito;s/d;2,25\n"
        "G-3;Entregado;;3\n",
        encoding="utf-8",
    )
    (tmp_path / "reports").mkdir()
    code, _, err = run(command[3:], capsys)
    assert code == 8
    assert err == (
        "check failed: column 'Fecha entrega' is missing in 1 of 2 rows where "
        "'Estado' is \"Entregado\" (data row 3)\n"
    )
    report = json.loads((tmp_path / "reports" / "envios.json").read_text(encoding="utf-8"))
    assert report["delimiter"] == ";"
    assert [(c["check"], c["column"], c["passed"]) for c in report["checks"]] == [
        ("max_missing", "Peso kg", True),
        ("unique", "Nro de guía", True),
        ("required_when", "Fecha entrega", False),
        ("required_column", "Nro de guía", True),
        ("required_column", "Estado", True),
        ("required_column", "Fecha entrega", True),
    ]
    # 1.234,5 was read with --decimal-comma --thousands dot.
    (_, _, _, weight) = report["columns"]
    assert (weight["type"], weight["max"]) == ("float", 1234.5)
