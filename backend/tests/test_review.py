"""Deterministic development regressions. These tests never call a model."""

import asyncio

import pytest
from pydantic import ValidationError

from app import agents
from app.cases import cases
from app.config import settings
from app.domain import Mapping, mapping_issues, parse_csv, schema_facts, validate_rows
from app.review import ModelFinding, assemble_findings, review_status, validator_results


def regression_case():
    return next(
        case for case in cases() if case.name == "country_optionality_review_regression"
    )


@pytest.mark.parametrize(
    "value,valid",
    [("IN", True), ("", True), ("ZZ", False), ("in", False), ("India", False)],
)
def test_optional_country_values_use_the_real_validator(value, valid):
    case = cases()[0]
    _, rows = parse_csv(case.csv)
    rows[0]["values"]["country_code"] = value
    result = validate_rows(rows, case.mapping, set())
    assert result["rows"][0]["valid"] is valid
    assert schema_facts()["fields"]["country_code"]["required"] is False
    assert schema_facts()["fields"]["country_code"]["blank_allowed"] is True


def test_optional_blank_claim_is_advisory_and_cannot_change_validation():
    case = regression_case()
    headers, rows = parse_csv(case.csv)
    before = case.mapping.model_dump()
    results = validator_results(case.mapping, headers, rows, set())
    false_claim = ModelFinding(
        field="country_code",
        issue_type="model_concern",
        severity="error",
        explanation="Optional means country_code must be blank.",
        scope="sample",
        validator_ids=["rows.country_code"],
    )
    findings = assemble_findings(results, [false_claim], [])
    concern = next(f for f in findings if f.field == "country_code")
    assert (
        concern.origin == "model_concern"
        and not concern.blocking
        and not concern.verified
    )
    assert concern.severity == "warning"
    assert case.mapping.model_dump() == before
    assert (
        next(result for result in results if result["id"] == "rows.country_code")[
            "invalid_rows"
        ]
        == 0
    )
    assert all(
        row["after"]["country_code"] in ("IN", None)
        for row in validate_rows(rows, case.mapping, set())["rows"]
    )
    assert not any(
        "country_code:" in error
        for row in validate_rows(rows, case.mapping, set())["rows"]
        for error in row["errors"]
    )


def test_slash_dates_and_format_mismatch_are_distinct_from_mapping_errors():
    case = regression_case()
    headers, rows = parse_csv(case.csv)
    assert mapping_issues(case.mapping, headers) == [
        "Select an explicit date format for signup_date"
    ]
    findings = assemble_findings(
        validator_results(case.mapping, headers, rows, set()), [], []
    )
    assert (
        findings[0].issue_type == "ambiguous_date"
        and findings[0].origin == "human_clarification"
    )
    assert review_status(findings) == "needs_attention"
    date = next(
        rule for rule in case.mapping.rules if rule.destination == "signup_date"
    )
    date.date_format = "%Y-%m-%d"
    assert mapping_issues(case.mapping, headers) == []
    results = validator_results(case.mapping, headers, rows, set())
    failed_date = next(
        result for result in results if result["id"] == "rows.signup_date"
    )
    assert (
        failed_date["invalid_rows"] == 4
        and failed_date["issue_type"] == "row_validation"
    )
    assert not any(
        result["issue_type"] in ("missing_mapping", "unknown_source")
        for result in results
    )
    date.date_format = "%d/%m/%Y"
    assert validate_rows(rows, case.mapping, set())["valid"] == 4


def test_sample_claims_cannot_claim_full_file_scope():
    with pytest.raises(ValidationError):
        ModelFinding(
            field="country_code",
            issue_type="model_concern",
            severity="error",
            explanation="All rows have IN.",
            scope="file",
        )
    sample = agents.sanitized_sample(*parse_csv(regression_case().csv))
    assert len(sample) == 3 and {row["country"] for row in sample} == {"IN"}


def test_restatement_keeps_known_validator_support_in_its_correct_category():
    case = regression_case()
    headers, rows = parse_csv(case.csv)
    results = validator_results(case.mapping, headers, rows, set())
    date_result = next(
        result for result in results if result["id"] == "mapping.signup_date.format"
    )
    repeated = ModelFinding(
        field="signup_date",
        issue_type="ambiguous_date",
        severity="error",
        explanation=date_result["explanation"],
        scope="mapping",
        evidence_ids=[date_result["id"]],
    )
    findings = assemble_findings(results, [repeated], [])
    assert len(findings) == 1
    assert findings[0].origin == "human_clarification"
    assert findings[0].validator_ids == [date_result["id"]]


def test_real_document_conflicts_have_a_separate_visible_category():
    model = ModelFinding(
        field="country_code",
        issue_type="documentation_conflict",
        severity="error",
        explanation="The supplied document requires country but the schema allows absence.",
        evidence_ids=["contradiction"],
        scope="documentation",
    )
    findings = assemble_findings(
        [], [model], [{"id": "contradiction", "text": "Country is required."}]
    )
    assert findings[0].origin == "documentation_conflict"
    assert findings[0].evidence_ids == ["contradiction"]
    assert not findings[0].blocking and not findings[0].verified


def test_review_gets_schema_and_full_file_results_without_investigator_prose(
    monkeypatch,
):
    case = regression_case()
    headers, rows = parse_csv(case.csv)
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    monkeypatch.setattr(
        agents,
        "retrieve",
        lambda *args: [{"id": "policy", "text": "country_code may be empty"}],
    )
    observed = []

    async def fake(name, schema, instruction, payload):
        observed.append((name, payload))
        if name == "Investigator":
            return agents.Proposal(mapping=case.mapping, findings=[]), {
                "input_tokens": 10,
                "output_tokens": 5,
            }
        assert (
            payload["destination_schema"]["fields"]["country_code"]["required"] is False
        )
        assert payload["sample_scope"]["rows_shown"] == 3
        assert payload["sample_scope"]["total_rows"] == 4
        assert (
            next(
                r for r in payload["validator_results"] if r["field"] == "country_code"
            )["checked_rows"]
            == 4
        )
        assert "proposal" not in payload and "schema" not in payload
        return agents.Review(findings=[]), {"input_tokens": 10, "output_tokens": 5}

    monkeypatch.setattr(agents, "adk_call", fake)
    _, run = asyncio.run(agents.suggest_mapping(None, headers, rows))
    assert [name for name, _ in observed] == ["Investigator", "Reviewer"]
    assert run["revision_count"] == 0
    assert run["usage"] == {"input_tokens": 20, "output_tokens": 10}
    assert run["status"] == "needs_attention"
    assert {f["field"] for f in run["findings"]} == {"signup_date"}
    assert run["calls"][1]["model_output"] == {"findings": []}


def test_model_concern_cannot_trigger_a_rule_rewriting_revision(monkeypatch):
    case = cases()[0]
    headers, rows = parse_csv(case.csv)
    rows[0]["values"]["country_code"] = "IN"
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    monkeypatch.setattr(
        agents,
        "retrieve",
        lambda *args: [{"id": "policy", "text": "Country is optional."}],
    )
    calls = []

    async def fake(name, schema, instruction, payload):
        calls.append(name)
        if name == "Investigator":
            return agents.Proposal(mapping=case.mapping, findings=[]), None
        return agents.Review(
            findings=[
                ModelFinding(
                    field="country_code",
                    issue_type="model_concern",
                    severity="error",
                    explanation="Optional country must be blank.",
                    evidence_ids=["policy"],
                    scope="mapping",
                )
            ]
        ), None

    monkeypatch.setattr(agents, "adk_call", fake)
    mapping, run = asyncio.run(agents.suggest_mapping(None, headers, rows))
    assert calls == ["Investigator", "Reviewer"]
    assert run["revision_count"] == 0 and run["status"] == "ready_for_human"
    assert validate_rows(rows, mapping, set())["valid"] == 1
    assert run["findings"][0]["origin"] == "model_concern"
    assert not run["findings"][0]["blocking"]


def test_date_transformation_change_invalidates_approval(client):
    case = regression_case()
    mapping = Mapping.model_validate(case.mapping.model_dump())
    date = next(rule for rule in mapping.rules if rule.destination == "signup_date")
    date.date_format = "%d/%m/%Y"
    item = client.post(
        "/api/uploads",
        files={"file": ("country-development.csv", case.csv, "text/csv")},
    ).json()
    url = "/api/uploads/" + item["id"]
    client.put(url + "/mapping", json=mapping.model_dump())
    item = client.post(url + "/validate").json()
    item = client.post(
        url + "/approve",
        json={
            "version": item["version"],
            "validation_hash": item["validation"]["hash"],
            "policy": "valid_only",
        },
    ).json()
    approval_id = item["approval"]["id"]
    date.date_format = "%Y-%m-%d"
    item = client.put(url + "/mapping", json=mapping.model_dump()).json()
    assert item["approval"] is None and item["validation"] is None
    assert (
        client.post(
            url + "/import",
            json={"approval_id": approval_id, "idempotency_key": "old-date-format"},
        ).status_code
        == 409
    )
    item = client.post(url + "/validate").json()
    assert item["validation"]["valid"] == 0 and item["validation"]["invalid"] == 4
