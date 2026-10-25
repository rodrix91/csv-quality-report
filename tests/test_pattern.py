"""Tests for ``--pattern NAME=REGEX`` (issue #155)."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from csv_quality_report import build_report, evaluate, read_table, render_markdown
from csv_quality_report.checks import CHECK_PATTERN, CHECK_REQUIRED_COLUMN, code_span
from csv_quality_report.cli import main
from csv_quality_report.profile import PatternProfile, _outside, compile_pattern, profile_file

WriteCsv = Callable[..., Path]
DATA = (
    "Cliente;CUIT;CP\n"
    "Ferretería;30-71000001-4;1425\n"
    "Almacén; 20-30000003-1 ;C1425ABC\n"
    "Kiosco;20300000049;C1425\n"
    "Panadería;;5000\n"
    "Librería;s/d;c1425abc\n"
    "Frigorífico;20300000049;X5000\n"
    "Mayorista;30 71000008 0;5000\n"
)
CUIT = r"\d{2}-\d{8}-\d"
CP = r"\d{4}|[A-Z]\d{4}[A-Z]{3}"


def measured(path: Path, name: str, pattern: str, top_n: int = 5) -> PatternProfile:
    report = profile_file(
        path, delimiter=";", na_tokens=("s/d",), top_n=top_n, patterns={name: pattern}
    )
    (found,) = report.patterns
    return found


# --- measuring in the profile ------------------------------------------------


def test_cells_that_do_not_match_are_counted_exactly(write_csv: WriteCsv) -> None:
    found = measured(write_csv(DATA), "CUIT", CUIT)
    # " 20-30000003-1 " is stripped and matches; "" and "s/d" are missing.
    assert found == PatternProfile(
        column="CUIT",
        pattern=CUIT,
        mismatched=3,
        examples=(("20300000049", 2), ("30 71000008 0", 1)),
    )


def test_the_whole_value_must_match(write_csv: WriteCsv) -> None:
    # re.search would accept "C1425" (it holds four digits) and re.match
    # "C1425ABC" for \d{4} alone; fullmatch applies the alternation to the
    # whole value, so "C1425" fails both branches.
    found = measured(write_csv(DATA), "CP", CP)
    assert (found.mismatched, found.examples) == (3, (("C1425", 1), ("c1425abc", 1), ("X5000", 1)))
    assert measured(write_csv(DATA), "CP", r"\d").mismatched == 7


def test_matching_is_case_sensitive_unless_the_pattern_says_otherwise(write_csv: WriteCsv) -> None:
    assert measured(write_csv(DATA), "CP", "(?i)" + CP).examples == (
        ("C1425", 1),
        ("X5000", 1),
    )


def test_examples_follow_top_n_and_ties_keep_first_seen(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    assert measured(path, "CP", r"\d{4}", top_n=2).examples == (("C1425ABC", 1), ("C1425", 1))
    assert measured(path, "CP", r"\d{4}", top_n=0) == PatternProfile("CP", r"\d{4}", 4)


def test_compile_pattern_refuses_empty_and_invalid_patterns() -> None:
    assert compile_pattern(CUIT).fullmatch("30-71000001-4")
    with pytest.raises(ValueError, match="a pattern must not be empty"):
        compile_pattern("")
    with pytest.raises(ValueError, match=r"invalid regular expression '\[': unterminated"):
        compile_pattern("[")


def test_profile_refuses_an_invalid_pattern_before_reading(write_csv: WriteCsv) -> None:
    with pytest.raises(ValueError, match="invalid regular expression"):
        profile_file(write_csv(DATA), delimiter=";", patterns={"CUIT": "("})


def test_unprofiled_and_unknown_columns_are_skipped(write_csv: WriteCsv) -> None:
    report = profile_file(
        write_csv(DATA), delimiter=";", columns=("Cliente",), patterns={"CUIT": CUIT, "X": "x"}
    )
    assert report.patterns == ()


def test_build_report_measures_the_same(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    table = read_table(path, delimiter=";")
    built = build_report(table, na_tokens=("s/d",), patterns={"CUIT": CUIT})
    assert built.patterns == (measured(path, "CUIT", CUIT),)


def test_no_patterns_no_profiles(write_csv: WriteCsv) -> None:
    assert profile_file(write_csv(DATA), delimiter=";").patterns == ()


# --- evaluate() ----------------------------------------------------------------


def test_evaluate_fails_and_describes(write_csv: WriteCsv) -> None:
    patterns = {"CUIT": CUIT}
    report = profile_file(write_csv(DATA), delimiter=";", na_tokens=("s/d",), patterns=patterns)
    (check,) = evaluate(report, patterns=patterns)
    assert (check.check, check.column, check.limit, check.value, check.passed) == (
        CHECK_PATTERN,
        "CUIT",
        0,
        3,
        False,
    )
    assert check.describe() == (
        r"column 'CUIT' has 3 cells that do not match the pattern `\d{2}-\d{8}-\d`: "
        '"20300000049" in 2 cells, "30 71000008 0" in 1 cell'
    )


def test_evaluate_passes(write_csv: WriteCsv) -> None:
    patterns = {"Cliente": r"\w+"}
    report = profile_file(write_csv(DATA), delimiter=";", patterns=patterns)
    (check,) = evaluate(report, patterns=patterns)
    assert check.passed and check.value == 0
    assert check.describe() == r"column 'Cliente' matches the pattern `\w+`"


def test_one_cell_and_no_examples(write_csv: WriteCsv) -> None:
    patterns = {"CUIT": r"[\d -]+"}
    report = profile_file(write_csv(DATA), delimiter=";", top_n=0, patterns=patterns)
    (check,) = evaluate(report, patterns=patterns)
    assert check.describe() == (
        r"column 'CUIT' has 1 cell that does not match the pattern `[\d -]+`"
    )


def test_evaluate_needs_the_same_pattern_in_the_report(write_csv: WriteCsv) -> None:
    report = profile_file(write_csv(DATA), delimiter=";", patterns={"CUIT": CUIT})
    with pytest.raises(ValueError, match="'CUIT' has a pattern check but the report"):
        evaluate(report, patterns={"CUIT": r"\d+"})
    with pytest.raises(ValueError, match="'CP' has a pattern check but the report"):
        evaluate(report, patterns={"CP": CP})
    with pytest.raises(ValueError, match="invalid regular expression"):
        evaluate(report, patterns={"CUIT": "["})


def test_unknown_and_unprofiled_columns(write_csv: WriteCsv) -> None:
    path = write_csv(DATA)
    checks = evaluate(profile_file(path, delimiter=";"), patterns={"CUlT": CUIT})
    assert [(c.check, c.column, c.passed) for c in checks] == [
        (CHECK_REQUIRED_COLUMN, "CUlT", False)
    ]
    narrow = profile_file(path, delimiter=";", columns=("Cliente",))
    with pytest.raises(ValueError, match="column 'CUIT' has a per-column check"):
        evaluate(narrow, patterns={"CUIT": CUIT})


# --- Markdown -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "span"),
    [
        (r"\d{4}", r"`\d{4}`"),
        ("a`b", "``a`b``"),
        ("`a``", "``` `a`` ```"),
        ("a\nb\rc", "`a b c`"),
    ],
)
def test_code_span(text: str, span: str) -> None:
    assert code_span(text) == span


def test_markdown_keeps_a_pattern_as_written(write_csv: WriteCsv) -> None:
    # Inside a code span a backslash shows as written, so the "|" of an
    # alternation is not escaped there, while the examples outside still are.
    path = write_csv("CP\n1425\nA|B\n")
    patterns = {"CP": CP}
    report = profile_file(path, patterns=patterns)
    markdown = render_markdown(report, str(path), checks=evaluate(report, patterns=patterns))
    assert (
        r"- FAIL: column 'CP' has 1 cell that does not match the pattern "
        r'`\d{4}|[A-Z]\d{4}[A-Z]{3}`: "A\|B" in 1 cell'
    ) in markdown


def test_markdown_escapes_a_pattern_without_a_bar_like_any_message(write_csv: WriteCsv) -> None:
    path = write_csv("CP\nA|B\n")
    report = profile_file(path, patterns={"CP": "[A-Z]"})
    markdown = render_markdown(report, str(path), checks=evaluate(report, patterns={"CP": "[A-Z]"}))
    assert r'pattern `[A-Z]`: "A\|B" in 1 cell' in markdown


# --- command line --------------------------------------------------------------


def run(write_csv: WriteCsv, *args: str) -> int:
    return main([str(write_csv(DATA)), "--delimiter", "auto", "--na", "s/d", *args])


def test_cli_fails_and_the_last_pattern_wins(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(write_csv, "--pattern", r"CUIT=\d+", "--pattern", r"CUIT=[\d-]+")
    out, err = capsys.readouterr()
    assert code == 8
    assert err == (
        r"check failed: column 'CUIT' has 1 cell that does not match the pattern `[\d-]+`: "
        '"30 71000008 0" in 1 cell\n'
    )
    assert out.count("the pattern") == 1


def test_cli_json(write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_csv, "--format", "json", "--pattern", f"CP={CP}") == 8
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check == {
        "check": "pattern",
        "column": "CP",
        "limit": 0,
        "value": 3,
        "passed": False,
        "pattern": CP,
        "mismatched": {"C1425": 1, "c1425abc": 1, "X5000": 1},
    }


def test_cli_name_ends_at_the_first_equals_sign(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    # The pattern keeps its own "=": a lookbehind, then a literal one.
    path = write_csv("Código;Nota\nA=1;x\nB=2;y\n")
    assert main([str(path), "--delimiter", ";", "--pattern", r"Código=[A-Z](?<=[AB])=\d"]) == 0
    assert r"column 'Código' matches the pattern `[A-Z](?<=[AB])=\d`" in capsys.readouterr().out


def test_cli_pattern_header_with_equals_uses_explicit_escape(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("SLA=met,shipment\nOK=10,S1\nOK=11,S2\nBAD,S3\n")
    assert main([str(path), "--format", "json", "--pattern", r"SLA\=met=OK=[0-9]+"]) == 8
    report = json.loads(capsys.readouterr().out)
    (check,) = report["checks"]
    assert check["column"] == "SLA=met"
    assert check["pattern"] == "OK=[0-9]+"
    assert check["value"] == 1
    assert check["mismatched"] == {"BAD": 1}


def test_cli_pattern_header_with_equals_can_pass(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv("SLA=met\nOK=10\nOK=11\n")
    assert main([str(path), "--pattern", r"SLA\=met=OK=[0-9]+"]) == 0
    assert "column 'SLA=met' matches" in capsys.readouterr().out


def test_cli_pattern_unseparated_escaped_equals_is_usage_error(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, "--pattern", r"CUIT\=test")
    assert exc.value.code == 2
    assert "invalid --pattern value" in capsys.readouterr().err


def test_without_the_option_reports_are_unchanged(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_csv, "--format", "json") == 0
    out = capsys.readouterr().out
    assert "pattern" not in out and "mismatched" not in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--pattern", "CUIT"], "invalid --pattern value: 'CUIT' (use NAME=REGEX"),
        (["--pattern", r"=\d"], r"invalid --pattern value: '=\\d' (use NAME=REGEX"),
        (["--pattern", "CUIT="], "invalid --pattern value: 'CUIT=' (use NAME=REGEX"),
        (
            ["--pattern", "CUIT=[0-9"],
            "invalid --pattern value for 'CUIT': invalid regular expression '[0-9': "
            "unterminated character set at position 0",
        ),
        (["--columns", "Cliente", "--pattern", "CUIT=x"], "--pattern checks column 'CUIT'"),
    ],
)
def test_cli_usage_errors(
    write_csv: WriteCsv, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(write_csv, *args)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


# --- counting the rejected values ------------------------------------------------


@pytest.mark.parametrize("top_n", [0, 1, 2, 5, 50])
def test_outside_matches_a_counter_of_the_rejected_values(top_n: int) -> None:
    # _outside streams the rejected values into heapq.nlargest instead of
    # building a Counter of them; the count and the examples, ties included,
    # must be what Counter.most_common gives.
    rng = random.Random(155)
    for _ in range(200):
        counts = Counter({f"v{rng.randrange(40)}": rng.randrange(1, 4) for _ in range(30)})
        keep = {f"v{i}" for i in range(40) if rng.random() < 0.4}
        expected = Counter({v: n for v, n in counts.items() if v not in keep})
        assert _outside(counts, keep.__contains__, top_n) == (
            expected.total(),
            tuple(expected.most_common(top_n)),
        )


def test_outside_with_top_0_still_counts_every_rejected_cell() -> None:
    # heapq.nlargest(0, ...) reads nothing; the drain after it counts the rest.
    assert _outside(Counter({"a": 2, "b": 3}), lambda value: False, 0) == (5, ())
