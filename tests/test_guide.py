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
    code, output = guide.run(guide.shlex.split(sample["args"]))
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
