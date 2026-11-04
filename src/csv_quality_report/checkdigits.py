"""Check-digit validation of identifiers (``--check-digit``).

A tax id or a barcode with a mistyped or swapped digit still has the right
format, so ``--pattern`` accepts it; its check digit does not match. Each
scheme here takes one value, as the report counts it (stripped of surrounding
whitespace), and says whether it is a valid identifier of that kind:

- ``cuit``: Argentine CUIT and CUIL, 11 digits, modulo 11 with the weights
  5, 4, 3, 2, 7, 6, 5, 4, 3, 2. A remainder that would need the check digit
  10 has no valid number (AFIP assigns another prefix instead).
- ``rut``: Chilean RUT and RUN, a body of 1 to 8 digits and a check digit
  ``0``-``9`` or ``K`` (either case), modulo 11 with the weights 2 to 7
  repeated from the right.
- ``cpf``: Brazilian CPF, 11 digits with two modulo-11 check digits.
- ``cnpj``: Brazilian CNPJ, 14 characters with two modulo-11 check digits.
  The first 12 may be digits or uppercase letters (the alphanumeric CNPJ the
  Receita Federal issues since July 2026), each worth its ASCII code minus
  48; the last 2 are digits.
- ``gtin``: GS1 barcodes (EAN-8, UPC-A, EAN-13 and GTIN-14), 8, 12, 13 or
  14 digits, modulo 10 with the weights 3 and 1 from the right.

The separators ``.``, ``-``, ``/`` and spaces are ignored wherever they
appear, so ``30-71000001-4``, ``30710000014`` and ``12.345.678-5`` are read
as written by hand or by an ERP; ``--pattern`` is the gate for a required
layout. CPF and CNPJ numbers made of one repeated digit (``111.111.111-11``)
pass the arithmetic but are not issued, so they are invalid.
"""

from __future__ import annotations

from collections.abc import Callable

_SEPARATORS = str.maketrans("", "", ".-/ ")
_DIGITS = frozenset("0123456789")
_CNPJ_BASE = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _compact(value: str) -> str:
    """Remove allowed separators; treat malformed non-text identifiers as invalid.

    Public validators also receive direct Python calls, including nullable
    values from dataframes. Such values cannot be identifiers and must return
    False instead of failing with AttributeError or TypeError.
    """
    if not isinstance(value, str):
        return ""
    return value.translate(_SEPARATORS)


def _all_digits(text: str) -> bool:
    """Whether ``text`` is made only of the ASCII digits 0-9 (``str.isdigit`` takes more)."""
    return _DIGITS.issuperset(text)


def _weighted(values: list[int], weights: list[int]) -> int:
    return sum(v * w for v, w in zip(values, weights, strict=True))


def _brazil_digit(values: list[int], weights: list[int]) -> int:
    """The modulo-11 check digit of CPF and CNPJ: 0 for a remainder below 2."""
    remainder = _weighted(values, weights) % 11
    return 0 if remainder < 2 else 11 - remainder


def valid_cuit(value: str) -> bool:
    """Whether ``value`` is an Argentine CUIT or CUIL with a matching check digit."""
    text = _compact(value)
    if len(text) != 11 or not _all_digits(text):
        return False
    digits = [int(ch) for ch in text]
    check = 11 - _weighted(digits[:10], [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]) % 11
    # 11 means 0; 10 matches no digit, so such a number is never valid.
    return (0 if check == 11 else check) == digits[10]


def valid_rut(value: str) -> bool:
    """Whether ``value`` is a Chilean RUT or RUN with a matching check digit."""
    text = _compact(value).upper()
    body, check = text[:-1], text[-1:]
    if not 1 <= len(body) <= 8 or not _all_digits(body):
        return False
    weights = [2, 3, 4, 5, 6, 7] * 2
    total = _weighted([int(ch) for ch in reversed(body)], weights[: len(body)])
    expected = 11 - total % 11
    return check == {11: "0", 10: "K"}.get(expected, str(expected))


def valid_cpf(value: str) -> bool:
    """Whether ``value`` is a Brazilian CPF with matching check digits."""
    text = _compact(value)
    if len(text) != 11 or not _all_digits(text) or len(set(text)) == 1:
        return False
    digits = [int(ch) for ch in text]
    # The CPF rule is 11 - (sum % 11), 0 when that is 10 or 11: the same as
    # the CNPJ rule, so both use _brazil_digit.
    first = _brazil_digit(digits[:9], list(range(10, 1, -1)))
    second = _brazil_digit(digits[:10], list(range(11, 1, -1)))
    return digits[9:] == [first, second]


def valid_cnpj(value: str) -> bool:
    """Whether ``value`` is a numeric or alphanumeric Brazilian CNPJ with matching check digits."""
    text = _compact(value)
    if len(text) != 14 or not _CNPJ_BASE.issuperset(text[:12]) or not _all_digits(text[12:]):
        return False
    if len(set(text)) == 1:
        return False
    values = [ord(ch) - 48 for ch in text]
    first = _brazil_digit(values[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = _brazil_digit(values[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return values[12:] == [first, second]


def valid_gtin(value: str) -> bool:
    """Whether ``value`` is a GS1 barcode number (EAN-8, UPC-A, EAN-13, GTIN-14)."""
    text = _compact(value)
    if len(text) not in (8, 12, 13, 14) or not _all_digits(text):
        return False
    # From the right, the digit before the check digit weighs 3, the next 1, ...
    total = 3 * sum(map(int, text[-2::-2])) + sum(map(int, text[-3::-2]))
    return -total % 10 == int(text[-1])


# Scheme name -> (validator, name used in messages).
SCHEMES: dict[str, tuple[Callable[[str], bool], str]] = {
    "cuit": (valid_cuit, "CUIT"),
    "rut": (valid_rut, "RUT"),
    "cpf": (valid_cpf, "CPF"),
    "cnpj": (valid_cnpj, "CNPJ"),
    "gtin": (valid_gtin, "GTIN"),
}


def check_scheme(scheme: str) -> str:
    """``scheme`` if it names a known scheme; ``ValueError`` naming the known ones otherwise."""
    if not isinstance(scheme, str) or scheme not in SCHEMES:
        known = ", ".join(SCHEMES)
        raise ValueError(f"unknown check-digit scheme {scheme!r} (use one of: {known})")
    return scheme


def scheme_label(scheme: str) -> str:
    """The validated identifier label, such as ``CUIT``; unknown schemes raise ValueError."""
    return SCHEMES[check_scheme(scheme)][1]


def validator(scheme: str) -> Callable[[str], bool]:
    """The function that validates one value of ``scheme`` (``ValueError`` if unknown)."""
    return SCHEMES[check_scheme(scheme)][0]
