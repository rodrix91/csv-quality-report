"""Verify a built wheel and its installed CLI outside the source checkout.

This deliberately uses a fresh virtual environment on the host OS, and drops
PYTHONPATH to catch packaging and console-entry-point regressions that source
tree unit tests alone cannot detect.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    fixture = root / "examples" / "tiny.csv"
    with tempfile.TemporaryDirectory(prefix="csv-quality-report-wheel-") as tmp:
        workspace = Path(tmp)
        wheel_dir = workspace / "dist"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
                str(root),
            ],
            check=True,
        )
        wheels = list(wheel_dir.glob("csv_quality_report-*.whl"))
        if len(wheels) != 1:
            raise AssertionError(f"expected one wheel, found: {wheels}")

        venv = workspace / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        binary = venv / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        command = binary / (
            "csv-quality-report.exe" if os.name == "nt" else "csv-quality-report"
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(wheels[0]),
            ],
            check=True,
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        version = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "from importlib.metadata import version; "
                    "from pathlib import Path; "
                    "import csv_quality_report; "
                    "assert version('csv-quality-report') == csv_quality_report.__version__; "
                    "assert Path(csv_quality_report.__file__).with_name('py.typed').is_file(); "
                    "print(csv_quality_report.__version__)"
                ),
            ],
            cwd=workspace,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        cli_version = subprocess.run(
            [str(command), "--version"],
            cwd=workspace,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if cli_version != f"csv-quality-report {version}":
            raise AssertionError(f"incorrect installed CLI version: {cli_version!r}")

        result = subprocess.run(
            [
                str(command),
                str(fixture),
                "--delimiter",
                "auto",
                "--min-rows",
                "1",
                "--format",
                "json",
            ],
            cwd=workspace,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(result.stdout)
        if report["rows"] < 1 or not report["columns"]:
            raise AssertionError("installed CLI returned an incomplete data-quality report")
        if not report["delimiter_detected"]:
            raise AssertionError("installed CLI did not perform delimiter auto-detection")

    print(f"Clean wheel install and console script: OK ({version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
