"""The commands and outputs in docs/guides/spanish-exports.md match real runs."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "update_guide", ROOT / "scripts" / "update_guide.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guide = _load_script()
TEXT = guide.GUIDE.read_text(encoding="utf-8")
SAMPLES = list(guide.SAMPLE_RE.finditer(TEXT))


def test_the_guide_has_samples() -> None:
    assert len(SAMPLES) >= 6
    # Every command block is followed by its output: none is left unmatched.
    assert TEXT.count("```console\n") == len(SAMPLES)


@pytest.mark.parametrize("sample", SAMPLES, ids=[m["args"].split()[0] for m in SAMPLES])
def test_sample_output_matches(sample: re.Match[str]) -> None:
    code, output = guide.run(guide.shlex.split(sample["args"]), guide.environment(sample["env"]))
    assert code in guide.REPORT_CODES, sample["args"]
    assert output == sample["output"], (
        "the guide is stale; run python scripts/update_guide.py and review the diff"
    )


def test_samples_use_corpus_files() -> None:
    for args in guide.samples(TEXT):
        assert args[0].startswith("tests/corpus/")
        assert (ROOT / args[0]).is_file(), args[0]


def test_update_is_a_no_op_on_a_fresh_guide() -> None:
    assert guide.update(TEXT) == TEXT


def test_update_refuses_a_command_that_fails() -> None:
    broken = "```console\n$ python -m csv_quality_report missing.csv\n```\n\n```markdown\n```"
    with pytest.raises(SystemExit, match="exited with 3"):
        guide.update(broken)


# --- environment assignments before the command (#140) ----------------------


def test_samples_may_set_a_fixed_clock() -> None:
    clocks = [m for m in SAMPLES if "SOURCE_DATE_EPOCH=" in m["env"]]
    assert len(clocks) >= 2
    assert all(guide.environment(m["env"])["SOURCE_DATE_EPOCH"].isdigit() for m in clocks)


def test_environment_parses_assignments() -> None:
    assert guide.environment("") == {}
    assert guide.environment("SOURCE_DATE_EPOCH=1791806400 TZ= ") == {
        "SOURCE_DATE_EPOCH": "1791806400",
        "TZ": "",
    }
    with pytest.raises(ValueError, match="not an environment assignment: 'python'"):
        guide.environment("python")
    with pytest.raises(ValueError, match="'lower=1'"):
        guide.environment("lower=1")
    with pytest.raises(ValueError, match="'SOURCE_DATE_EPOCH'"):
        guide.environment("SOURCE_DATE_EPOCH")


def test_update_refuses_a_sample_with_a_bad_assignment() -> None:
    sample = (
        "```console\n$ sudo python -m csv_quality_report tests/corpus/stock_counts_week1.csv\n"
        "```\n\n```markdown\n```"
    )
    assert [m["env"] for m in guide.SAMPLE_RE.finditer(sample)] == ["sudo "]
    with pytest.raises(ValueError, match="not an environment assignment: 'sudo'"):
        guide.update(sample)


def test_run_sets_the_environment_only_while_the_command_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1791237600")
    monkeypatch.delenv("CSVQR_GUIDE_UNSET", raising=False)
    args = ["tests/corpus/stock_counts_week1.csv", "--delimiter", "auto", "--decimal-comma"]
    stale = args + ["--baseline", "tests/corpus/expected/stock_counts_week1_stamped.json"]
    stale += ["--max-baseline-age", "1d"]
    fresh_code, _ = guide.run(stale)
    stale_code, output = guide.run(
        stale, {"SOURCE_DATE_EPOCH": "1792411200", "CSVQR_GUIDE_UNSET": "1"}
    )
    assert (fresh_code, stale_code) == (0, 8)
    assert "the baseline is 13 days 14 hours old" in output
    assert guide.os.environ["SOURCE_DATE_EPOCH"] == "1791237600"
    assert "CSVQR_GUIDE_UNSET" not in guide.os.environ


def test_run_restores_the_environment_when_the_command_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    code, _ = guide.run(["tests/corpus/missing.csv"], {"SOURCE_DATE_EPOCH": "1792411200"})
    assert code == 3
    assert "SOURCE_DATE_EPOCH" not in guide.os.environ

    def crash(args: list[str]) -> int:
        assert guide.os.environ["SOURCE_DATE_EPOCH"] == "1792411200"
        raise RuntimeError("boom")

    monkeypatch.setattr(guide, "cli_main", crash)
    with pytest.raises(RuntimeError, match="boom"):
        guide.run(["tests/corpus/stock_counts_week1.csv"], {"SOURCE_DATE_EPOCH": "1792411200"})
    assert "SOURCE_DATE_EPOCH" not in guide.os.environ


def test_update_runs_a_sample_with_its_environment() -> None:
    sample = (
        "```console\n$ SOURCE_DATE_EPOCH=1792411200 python -m csv_quality_report "
        "tests/corpus/stock_counts_week1.csv --delimiter auto --decimal-comma "
        "--baseline tests/corpus/expected/stock_counts_week1_stamped.json "
        "--max-baseline-age 8d\n```\n\n```markdown\n```"
    )
    assert "- FAIL: the baseline is 13 days 14 hours old" in guide.update(sample)
