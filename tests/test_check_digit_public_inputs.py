"""Public check-digit validators should reject nullable or non-text inputs safely."""

from __future__ import annotations

import math

import pytest

from csv_quality_report.checkdigits import (
    SCHEMES,
    valid_cnpj,
    valid_cpf,
    valid_cuit,
    valid_gtin,
    valid_rut,
    validator,
)

VALID_EXAMPLES = {
    "cuit": "33-69345023-9",
    "rut": "60.803.000-K",
    "cpf": "529.982.247-25",
    "cnpj": "12.ABC.345/01DE-35",
    "gtin": "4006381333931",
}


@pytest.mark.parametrize("scheme", list(SCHEMES))
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        0,
        12345678901,
        12.5,
        math.nan,
        math.inf,
        b"4006381333931",
        bytearray(b"4006381333931"),
        [],
        {},
        object(),
    ],
)
def test_non_string_identifiers_are_invalid_without_raising(scheme: str, invalid: object) -> None:
    # A nullable or untyped Python data source can pass numbers and missing
    # values directly into the validators, unlike the CLI CSV parser.
    assert validator(scheme)(invalid) is False  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("scheme", "check"),
    [
        ("cuit", valid_cuit),
        ("rut", valid_rut),
        ("cpf", valid_cpf),
        ("cnpj", valid_cnpj),
        ("gtin", valid_gtin),
    ],
)
def test_existing_text_identifiers_are_unchanged(scheme: str, check: object) -> None:
    assert callable(check)
    assert validator(scheme)(VALID_EXAMPLES[scheme]) is True
    assert validator(scheme)("") is False
    assert validator(scheme)("this-is-not-an-identifier") is False
