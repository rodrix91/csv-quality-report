"""Bounded, non-disclosing diagnostics for public check-digit scheme selection."""

from __future__ import annotations

import pytest

from csv_quality_report.checkdigits import check_scheme, scheme_label, validator


@pytest.mark.parametrize(
    "invalid",
    [
        "secret-prefix-" + "x" * 50_000 + "-private-tail",
        "bad\n::error::forged\x1b[31m" + "a" * 10_000,
        "\u202e" * 10_000 + "sensitive-ending",
        "\x00" * 100 + "hidden-secret",
    ],
    ids=["long-ascii", "terminal-controls", "bidi-controls", "nul-controls"],
)
def test_invalid_scheme_diagnostic_is_short_escaped_and_redacted(invalid: str) -> None:
    for operation in (check_scheme, validator, scheme_label):
        with pytest.raises(ValueError, match="unknown check-digit scheme") as caught:
            operation(invalid)
        message = str(caught.value)
        assert len(message) < 300
        assert "[truncated]" in message
        assert "-private-tail" not in message
        assert "sensitive-ending" not in message
        assert "hidden-secret" not in message
        assert "forged" not in message or "\\n" in message
        assert "\n" not in message
        assert "\r" not in message
        assert "\x1b" not in message
        assert "\u202e" not in message


def test_non_string_scheme_does_not_invoke_user_controlled_repr() -> None:
    class DangerousRepr:
        def __repr__(self) -> str:
            raise AssertionError("untrusted repr must not run")

    invalid_inputs: tuple[object, ...] = (None, [], {}, DangerousRepr())
    for invalid in invalid_inputs:
        with pytest.raises(ValueError, match="unknown check-digit scheme <non-string>"):
            check_scheme(invalid)  # type: ignore[arg-type]


def test_normal_scheme_selection_and_existing_short_message_are_preserved() -> None:
    assert check_scheme("cuit") == "cuit"
    assert check_scheme("gtin") == "gtin"
    with pytest.raises(ValueError) as caught:
        check_scheme("CUIT")
    assert str(caught.value) == (
        "unknown check-digit scheme 'CUIT' (use one of: cuit, rut, cpf, cnpj, gtin)"
    )
