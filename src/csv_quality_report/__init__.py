"""csv-quality-report: quick data-quality report for a CSV file.

The command line is the main interface; the names below are the supported
Python API (see "Use from Python" in the README)::

    from csv_quality_report import evaluate, profile_file, render_markdown

    report = profile_file(Path("shipments.csv"), delimiter="auto")
    checks = evaluate(report, max_missing=5)
    print(render_markdown(report, "shipments.csv", checks))

Every module path used before (``csv_quality_report.profile`` and so on)
keeps working.
"""

__version__ = "0.3.0"

from .checks import CheckResult, evaluate
from .errors import CsvQualityError
from .profile import ColumnProfile, Report, build_report, profile_file
from .reader import read_table
from .render import render_json, render_markdown

__all__ = [
    "CheckResult",
    "ColumnProfile",
    "CsvQualityError",
    "Report",
    "__version__",
    "build_report",
    "evaluate",
    "profile_file",
    "read_table",
    "render_json",
    "render_markdown",
]
