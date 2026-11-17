"""Structured review grounded in deterministic results and explicit scope."""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .domain import FIELDS, REQUIRED, Mapping, validate_rows

FieldName = Literal[
    "name", "email", "signup_date", "subscription_tier", "country_code", "file"
]
IssueType = Literal[
    "missing_mapping",
    "unknown_source",
    "date_format_required",
    "ambiguous_date",
    "row_validation",
    "unsupported_transform",
    "citation_support",
    "documentation_conflict",
    "model_concern",
    "human_clarification",
]


class ModelFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: FieldName
    issue_type: IssueType
    severity: Literal["info", "warning", "error"]
    explanation: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    validator_ids: list[str] = Field(default_factory=list, max_length=10)
    scope: Literal["sample", "mapping", "documentation"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: FieldName
    issue_type: IssueType
    severity: Literal["info", "warning", "error"]
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)
    validator_ids: list[str] = Field(default_factory=list)
    scope: Literal["sample", "mapping", "documentation", "file"]
    origin: Literal[
        "validator", "human_clarification", "model_concern", "documentation_conflict"
    ]
    verified: bool
    blocking: bool


def validator_results(
    mapping: Mapping, headers: list[str], rows: list[dict], existing: set[str]
) -> list[dict]:
    """Use the real engine over all rows, exporting counts/errors without PII."""
    results = []
    rules = {rule.destination: rule for rule in mapping.rules}
    for field in REQUIRED:
        if field not in rules:
            results.append(
                {
                    "id": f"mapping.{field}.missing",
                    "field": field,
                    "issue_type": "missing_mapping",
                    "status": "fail",
                    "scope": "mapping",
                    "explanation": f"Missing required mapping: {field}",
                    "repairable": True,
                }
            )
    for rule in mapping.rules:
        if rule.source not in headers:
            results.append(
                {
                    "id": f"mapping.{rule.destination}.source",
                    "field": rule.destination,
                    "issue_type": "unknown_source",
                    "status": "fail",
                    "scope": "mapping",
                    "explanation": f"Unknown source column: {rule.source}",
                    "repairable": True,
                }
            )
    date = rules.get("signup_date")
    if date and not date.date_format:
        slash = any("/" in row["values"].get(date.source, "") for row in rows)
        results.append(
            {
                "id": "mapping.signup_date.format",
                "field": "signup_date",
                "issue_type": "ambiguous_date" if slash else "date_format_required",
                "status": "needs_input",
                "scope": "mapping",
                "repairable": False,
                "explanation": "Slash date order requires explicit human selection. Select an explicit date format for signup_date."
                if slash
                else "Select an explicit date format for signup_date.",
            }
        )
    validation = validate_rows(rows, mapping, existing)
    for field in FIELDS:
        if field not in rules or (field == "signup_date" and not date.date_format):
            continue
        invalid_rows = [
            row
            for row in validation["rows"]
            if any(error.startswith(field + ":") for error in row["errors"])
        ]
        errors = Counter(
            error
            for row in invalid_rows
            for error in row["errors"]
            if error.startswith(field + ":")
        )
        results.append(
            {
                "id": f"rows.{field}",
                "field": field,
                "issue_type": "row_validation",
                "status": "fail" if invalid_rows else "pass",
                "scope": "file",
                "checked_rows": len(rows),
                "invalid_rows": len(invalid_rows),
                "row_numbers": [row["row_number"] for row in invalid_rows[:20]],
                "errors": dict(errors),
                "repairable": False,
                "explanation": f"{field}: {len(invalid_rows)} of {len(rows)} rows fail value validation."
                if invalid_rows
                else f"{field}: all {len(rows)} rows pass value validation.",
            }
        )
    return results


def assemble_findings(
    results: list[dict], model_findings: list[ModelFinding], evidence: list[dict]
) -> list[Finding]:
    """Only application results can establish errors or blocking status.

    Model/document concerns remain visible and advisory, including when a model
    cites a passing validator. Referencing an ID does not prove its claim.
    """
    findings = []
    for result in results:
        if result["status"] == "pass":
            continue
        human = result["status"] == "needs_input"
        findings.append(
            Finding(
                field=result["field"],
                issue_type=result["issue_type"],
                severity="warning" if human else "error",
                explanation=result["explanation"],
                validator_ids=[result["id"]],
                scope=result["scope"],
                origin="human_clarification" if human else "validator",
                verified=True,
                blocking=True,
            )
        )
    evidence_ids = {item["id"] for item in evidence}
    result_ids = {item["id"] for item in results}
    for model in model_findings:
        # A supplied sample can support observations only about that sample.
        # Deterministic full-file results are rendered separately above.
        conflict = model.issue_type == "documentation_conflict"
        data = model.model_dump()
        references = list(dict.fromkeys(model.evidence_ids + model.validator_ids))
        data["evidence_ids"] = [ref for ref in references if ref in evidence_ids]
        data["validator_ids"] = [ref for ref in references if ref in result_ids]
        # An exact restatement of an authoritative result is already rendered.
        # Preserve known support IDs even if a model used the wrong ID list.
        if any(
            f.verified
            and f.field == model.field
            and f.issue_type == model.issue_type
            and f.explanation == model.explanation
            and set(f.validator_ids) & set(data["validator_ids"])
            for f in findings
        ):
            continue
        data["severity"] = "info" if model.severity == "info" else "warning"
        if model.scope == "sample":
            data["explanation"] = "Sample-only model concern. " + model.explanation
        finding = Finding(
            **data,
            origin="documentation_conflict" if conflict else "model_concern",
            verified=False,
            blocking=False,
        )
        if not any(
            existing.model_dump() == finding.model_dump() for existing in findings
        ):
            findings.append(finding)
    return findings


def review_status(findings: list[Finding]) -> str:
    return "needs_attention" if any(f.blocking for f in findings) else "ready_for_human"
