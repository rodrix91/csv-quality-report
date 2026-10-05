"""Error types and process exit codes."""

from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2  # argparse uses 2 for usage errors
EXIT_IO = 3
EXIT_ENCODING = 4
EXIT_EMPTY = 5
EXIT_RAGGED = 6
EXIT_DELIMITER = 7
EXIT_CHECKS = 8  # report produced, but a --max-* quality threshold failed


class CsvQualityError(Exception):
    """Base class: carries a human-readable message and an exit code."""

    exit_code: int = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FileReadError(CsvQualityError):
    exit_code = EXIT_IO


class EncodingError(CsvQualityError):
    exit_code = EXIT_ENCODING


class EmptyFileError(CsvQualityError):
    exit_code = EXIT_EMPTY


class RaggedRowError(CsvQualityError):
    exit_code = EXIT_RAGGED


class DelimiterDetectionError(CsvQualityError):
    exit_code = EXIT_DELIMITER
