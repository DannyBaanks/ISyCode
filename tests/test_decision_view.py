import pytest

from isycode.decision_view import denied_line, verified_receipt_line


def test_verified_receipt_line_local():
    line = verified_receipt_line("abc123456789extra", local=True)
    assert line == "ISySentinel ALLOW · local receipt abc123456789 verified"


def test_verified_receipt_line_non_local():
    line = verified_receipt_line("xyz987654321000", local=False)
    assert line == "ISySentinel ALLOW · receipt xyz987654321 verified"


def test_verified_receipt_line_validation():
    with pytest.raises(ValueError, match="receipt id must be a short string"):
        verified_receipt_line("")

    with pytest.raises(ValueError, match="receipt id must be a short string"):
        verified_receipt_line("a" * 81)

    with pytest.raises(ValueError, match="receipt id must be a short string"):
        verified_receipt_line(None)  # type: ignore[arg-type]


def test_denied_line_normal():
    line = denied_line("file is read only")
    assert line == "ISySentinel DENY · file is read only"


def test_denied_line_empty_or_none():
    assert denied_line("") == "ISySentinel DENY · denied"
    assert denied_line("   ") == "ISySentinel DENY · denied"
    assert denied_line(None) == "ISySentinel DENY · denied"  # type: ignore[arg-type]


def test_denied_line_whitespace_collapse_and_truncation():
    line = denied_line("bad   permission \n\t attempted")
    assert line == "ISySentinel DENY · bad permission attempted"

    long_reason = "x" * 300
    line_truncated = denied_line(long_reason)
    assert line_truncated == f"ISySentinel DENY · {'x' * 240}"
