import pytest
from pydantic import ValidationError

from app.cases import cases
from app.config import settings
from app.domain import Mapping, Rule, error_csv, parse_csv, safe_cell, validate_rows


@pytest.mark.parametrize("case", cases(), ids=lambda c: c.name)
def test_ground_truth(case):
    if case.parse_error:
        with pytest.raises(ValueError):
            parse_csv(case.csv)
        return
    _, rows = parse_csv(case.csv)
    result = validate_rows(rows, case.mapping, set())
    actual = {r["row_number"]: r["errors"] for r in result["rows"] if not r["valid"]}
    assert actual.keys() == case.errors.keys()
    for row, errors in case.errors.items():
        for error in errors:
            assert any(error in e for e in actual[row])


def test_limits_and_encoding(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    with pytest.raises(ValueError, match="byte limit"):
        parse_csv(b"headers\n" + b"a" * 15)
    monkeypatch.setattr(settings, "max_upload_bytes", 1000)
    monkeypatch.setattr(settings, "max_rows", 1)
    with pytest.raises(ValueError, match="row limit"):
        parse_csv(b"name\na\nb\n")
    monkeypatch.setattr(settings, "max_columns", 1)
    with pytest.raises(ValueError, match="columns"):
        parse_csv(b"name,email\na,b\n")
    assert parse_csv(b"\xef\xbb\xbfname\nAlice\n")[0] == ["name"]


def test_no_arbitrary_transformations():
    with pytest.raises(ValidationError):
        Rule(destination="name", source="a", python="print(1)")
    with pytest.raises(ValidationError):
        Rule(destination="email", source="a", date_format="%Y-%m-%d")
    with pytest.raises(ValidationError):
        Mapping(rules=[Rule(destination="name", source="a")] * 2)


@pytest.mark.parametrize(
    "value", ["=SUM(A1)", "+cmd", "-cmd", "@cmd", "  =cmd", "\t=cmd"]
)
def test_formula_safety(value):
    assert safe_cell(value).startswith("'")


def test_report_mode_and_original_lines():
    case = next(c for c in cases() if c.name == "invalid_email")
    _, rows = parse_csv(case.csv)
    result = validate_rows(rows, case.mapping, set())
    report = error_csv(result, "mock")
    assert "mock,2," in report
    assert "bad-address" in report
