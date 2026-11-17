"""Opt-in sequential local evaluation. Answer labels never enter agent payloads."""

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import re
import statistics
import time
from pathlib import Path

from pydantic import ValidationError

from .agents import ALIASES, TIER_ALIASES, suggest_mapping
from .assessment_cases import RUBRIC, assessment_cases
from .config import settings
from .domain import FIELDS, Mapping, Rule, mapping_issues, schema_facts
from .local_provider import diagnostics
from .models import DB
from .review import validator_results


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def normalized_header(value):
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def source_rows(case):
    return [
        {
            "row_number": index + 2,
            "values": dict(zip(case["headers"], row, strict=True)),
        }
        for index, row in enumerate(case["rows"])
    ]


def baseline(case):
    """Fixed existing aliases after ASCII separator/case normalization.

    Competing matches abstain. ISO shape selects ISO parsing, every slash leaves
    null. Only the existing documented tier aliases can be substituted.
    """
    rules = []
    for field in FIELDS:
        accepted = {normalized_header(alias) for alias in ALIASES[field]}
        matches = [
            header
            for header in case["headers"]
            if normalized_header(header) in accepted
        ]
        if len(matches) != 1:
            continue
        source = matches[0]
        values = [row["values"][source].strip() for row in source_rows(case)]
        rule = Rule(destination=field, source=source)
        if field == "signup_date" and all(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in values
        ):
            rule.date_format = "%Y-%m-%d"
        if field == "subscription_tier":
            rule.categories = {
                value: TIER_ALIASES[value] for value in values if value in TIER_ALIASES
            }
        rules.append(rule)
    return Mapping(rules=rules)


def mapping_score(mapping, case):
    by_field = {rule.destination: rule for rule in mapping.rules}
    correct_sources = {}
    errors = {}
    unsupported = []
    for field in FIELDS:
        expected = case["expected"][field]
        rule = by_field.get(field)
        correct_sources[field] = (rule.source if rule else None) in expected["sources"]
        issues = []
        if not correct_sources[field]:
            issues.append("source")
        if rule:
            if not rule.trim:
                issues.append("trim")
            if (
                field == "signup_date"
                and rule.date_format not in expected["date_formats"]
            ):
                issues.append("date_format")
            values = {
                row["values"].get(rule.source, "").strip() for row in source_rows(case)
            }
            actual_pairs = {
                key: value for key, value in rule.categories.items() if key != value
            }
            effective = {
                key: value for key, value in actual_pairs.items() if key in values
            }
            if effective != expected["categories"]:
                issues.append("categories")
            for source, target in actual_pairs.items():
                if field != "subscription_tier" or TIER_ALIASES.get(source) != target:
                    unsupported.append(
                        {"field": field, "source": source, "target": target}
                    )
                    if "categories" not in issues:
                        issues.append("categories")
        elif expected["categories"]:
            issues.append("categories")
        if issues:
            errors[field] = issues
    dates = [rule for rule in mapping.rules if rule.destination == "signup_date"]
    needs_date = case["required_human_decisions"].get("signup_date") == "date_selection"
    return {
        "correct_sources": correct_sources,
        "source_correct": sum(correct_sources.values()),
        "exact": not errors,
        "errors": errors,
        "unsupported_categories": unsupported,
        "date_clarification_correct": bool(
            dates and correct_sources["signup_date"] and dates[0].date_format is None
        )
        if needs_date
        else None,
    }


def citation_support(mapping, evidence):
    by_id = {chunk["id"]: chunk for chunk in evidence}
    claims = []
    for rule in mapping.rules:
        for source, target in rule.categories.items():
            if source == target:
                continue
            supports = [by_id[ref] for ref in rule.citations if ref in by_id]
            supported = (
                rule.destination == "subscription_tier"
                and TIER_ALIASES.get(source) == target
                and any(
                    chunk["document"] == "04-approved-aliases.md"
                    and f"{source} → {target}" in chunk["text"]
                    for chunk in supports
                )
            )
            claims.append(
                {
                    "field": rule.destination,
                    "source": source,
                    "target": target,
                    "supported_by_rubric": supported,
                    "citations": rule.citations,
                }
            )
    return claims


def aggregate(records):
    summary = {}
    for variant in ("baseline", "investigator", "investigator_reviewer"):
        selected = [record for record in records if record["variant"] == variant]
        completed = [record for record in selected if record["success"]]
        summary[variant] = {
            "attempted": len(selected),
            "completed": len(completed),
            "structured_failures": sum(
                record.get("failure_type") == "structured_output" for record in selected
            ),
            "runtime_failures": sum(
                not record["success"]
                and record.get("failure_type") != "structured_output"
                for record in selected
            ),
            "source_correct": sum(
                record["score"]["source_correct"] for record in completed
            ),
            "source_denominator": len(selected) * 5,
            "per_field": {
                field: {
                    "correct": sum(
                        record["score"]["correct_sources"][field]
                        for record in completed
                    ),
                    "denominator": len(selected),
                }
                for field in FIELDS
            },
            "exact_correct": sum(record["score"]["exact"] for record in completed),
            "exact_denominator": len(selected),
            "unsupported_pairs_observed": sum(
                len(record["score"]["unsupported_categories"]) for record in completed
            ),
            "date_clarification_correct": sum(
                record["score"]["date_clarification_correct"] is True
                for record in completed
            ),
            "date_clarification_denominator": sum(
                record.get("requires_date_selection", False) for record in selected
            ),
            "median_wall_ms": statistics.median(
                record["wall_ms"] for record in selected
            )
            if selected
            else None,
            "mean_wall_ms": statistics.mean(record["wall_ms"] for record in selected)
            if selected
            else None,
            "input_tokens_known": sum(
                record.get("run", {}).get("usage", {}).get("input_tokens", 0)
                for record in completed
                if record.get("run", {}).get("usage")
            ),
            "output_tokens_known": sum(
                record.get("run", {}).get("usage", {}).get("output_tokens", 0)
                for record in completed
                if record.get("run", {}).get("usage")
            ),
            "usage_complete": all(
                record.get("run", {}).get("usage") is not None for record in selected
            ),
            "citation_ids": {
                "valid": sum(
                    record.get("run", {}).get("citation_audit", {}).get("valid", 0)
                    for record in completed
                ),
                "proposed": sum(
                    record.get("run", {}).get("citation_audit", {}).get("proposed", 0)
                    for record in completed
                ),
            },
            "supported_category_claims": sum(
                claim["supported_by_rubric"]
                for record in completed
                for claim in record.get("category_evidence", [])
            ),
            "category_claim_denominator": sum(
                len(record.get("category_evidence", [])) for record in completed
            ),
        }
    return summary


def code_manifest():
    paths = sorted(
        [
            *Path("app").glob("*.py"),
            *Path("knowledge").glob("*.md"),
            *Path(".").glob("requirements*.txt"),
        ]
    )
    hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }
    return {
        "source_digest": sha(hashes),
        "files": hashes,
        "revision_method": "Content-addressed backend/knowledge/dependency revision.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--freeze-labels", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    cases = assessment_cases()
    labels = {
        "rubric": RUBRIC,
        "cases": cases,
        "case_hashes": {case["id"]: sha(case) for case in cases},
    }
    label_file = root / "predeclared-labels.json"
    if args.freeze_labels:
        if label_file.exists():
            raise SystemExit(
                "Labels already frozen. Preserve them; select a new evaluation version for changes."
            )
        label_file.write_text(
            json.dumps(
                {"frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(), **labels},
                indent=2,
            )
        )
        print(json.dumps({"cases": len(cases), "label_digest": sha(labels)}))
        return
    frozen = json.loads(label_file.read_text())
    if any(frozen[key] != labels[key] for key in labels):
        raise SystemExit(
            "Frozen labels differ; do not continue this evaluation version"
        )
    if not args.run or settings.ai_mode != "local":
        raise SystemExit("Real evaluation requires --run and AI_MODE=local")
    if not settings.database_url.split("?")[0].endswith("/databridge_test"):
        raise SystemExit("Use the dedicated databridge_test database")
    output = root / "results.json"
    if output.exists():
        raise SystemExit("Results already exist; preserve the first pass")
    manifest = {
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "labels_digest": sha(labels),
        "code": code_manifest(),
        "runtime": diagnostics(),
        "schema": schema_facts(),
        "config": {
            name: getattr(settings, name)
            for name in (
                "local_model",
                "local_embedding_model",
                "local_context",
                "local_output_tokens",
                "local_timeout_seconds",
            )
        },
        "baseline_aliases": ALIASES,
        "baseline_tier_aliases": TIER_ALIASES,
        "ordering": "Baseline first; alternate I/IR then IR/I by case index, sequentially. One development warm-up precedes measurements.",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    from .cases import cases as development_cases
    from .domain import parse_csv

    warm = next(
        case
        for case in development_cases()
        if case.name == "country_optionality_review_regression"
    )
    with DB() as db:
        headers, rows = parse_csv(warm.csv)
        _, warm_run = asyncio.run(suggest_mapping(db, headers, rows, reviewer=True))
    (root / "warmup.json").write_text(json.dumps(warm_run, indent=2))
    records = []
    for index, case in enumerate(cases):
        variants = (
            ("baseline", "investigator", "investigator_reviewer")
            if index % 2 == 0
            else ("baseline", "investigator_reviewer", "investigator")
        )
        for variant in variants:
            started = time.monotonic()
            record = {
                "case": case["id"],
                "case_hash": sha(case),
                "variant": variant,
                "requires_date_selection": case["required_human_decisions"].get(
                    "signup_date"
                )
                == "date_selection",
            }
            try:
                if variant == "baseline":
                    mapping = baseline(case)
                    run = {
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                        "calls": [],
                        "evidence": [],
                    }
                else:
                    with DB() as db:
                        mapping, run = asyncio.run(
                            suggest_mapping(
                                db,
                                case["headers"],
                                source_rows(case),
                                reviewer=variant == "investigator_reviewer",
                            )
                        )
                record.update(
                    success=True,
                    mapping=mapping.model_dump(),
                    run=run,
                    score=mapping_score(mapping, case),
                    mapping_issues=mapping_issues(mapping, case["headers"]),
                    validator_results=validator_results(
                        mapping, case["headers"], source_rows(case), set()
                    ),
                    category_evidence=citation_support(mapping, run["evidence"])
                    if variant != "baseline"
                    else [],
                )
                record["initial_investigator"] = next(
                    (
                        call["model_output"]
                        for call in run["calls"]
                        if call["agent"] == "Investigator"
                    ),
                    None,
                )
                record["reviewed_proposals"] = [
                    {
                        "call_index": number,
                        "score": mapping_score(
                            Mapping.model_validate(call["input"]["payload"]["mapping"]),
                            case,
                        ),
                        "findings": call["model_output"]["findings"],
                    }
                    for number, call in enumerate(run["calls"])
                    if call["agent"] == "Reviewer"
                ]
            except Exception as exc:
                record.update(
                    success=False,
                    failure_type="structured_output"
                    if isinstance(exc, ValidationError)
                    else "runtime",
                    error_type=type(exc).__name__,
                    error="Strict structured-output validation failed"
                    if isinstance(exc, ValidationError)
                    else str(exc)[:350],
                    partial_calls=getattr(exc, "agent_calls", []),
                )
            record["wall_ms"] = round((time.monotonic() - started) * 1000, 3)
            records.append(record)
            output.write_text(
                json.dumps(
                    {
                        "manifest": manifest,
                        "records": records,
                        "summary": aggregate(records),
                        "complete": False,
                    },
                    indent=2,
                )
            )
            print(
                json.dumps(
                    {
                        key: record.get(key)
                        for key in (
                            "case",
                            "variant",
                            "success",
                            "wall_ms",
                            "failure_type",
                        )
                    }
                ),
                flush=True,
            )
    result = {
        "manifest": manifest,
        "records": records,
        "summary": aggregate(records),
        "complete": True,
        "code_unchanged_during_run": code_manifest()["source_digest"]
        == manifest["code"]["source_digest"],
    }
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
