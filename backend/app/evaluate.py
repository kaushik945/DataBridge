"""Explicitly destructive evaluation in the dedicated databridge_test database only."""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from .agents import suggest_mapping
from .cases import cases
from .config import settings
from .domain import FIELDS, mapping_issues, parse_csv, validate_rows
from .main import app
from .models import Base, Customer, DB, Operator, engine
from .retrieval import ingest


def comparable(mapping):
    return {
        r.destination: {
            "source": r.source,
            "trim": r.trim,
            "date_format": r.date_format,
            "categories": r.categories,
        }
        for r in mapping.rules
    }


async def evaluate(split="all", limit=None, names=None):
    selected = [c for c in cases() if split == "all" or c.split == split]
    if names:
        selected = [c for c in selected if c.name in names]
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise SystemExit("No cases selected")
    if not settings.database_url.split("?")[0].endswith("/databridge_test"):
        raise SystemExit(
            "Evaluation resets data: DATABASE_URL must name databridge_test"
        )
    # Dedicated synthetic runner must not exhaust the interactive upload allowance.
    settings.uploads_per_minute = 1000
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)
        conn.execute(text("TRUNCATE " + ", ".join(Base.metadata.tables) + " CASCADE"))
    password = "evaluation-only-password"
    with DB() as db:
        db.add(
            Operator(
                username="evaluator", password_hash=PasswordHasher().hash(password)
            )
        )
        db.commit()
        ingest(
            db,
            Path("knowledge")
            if Path("knowledge").exists()
            else Path("../docs/knowledge"),
        )
    results = {
        "mode": settings.ai_mode,
        "case_count": len(selected),
        "split": split,
        "model": settings.local_model
        if settings.ai_mode == "local"
        else settings.vertex_model or None,
        "pricing_date": settings.pricing_date or None,
        "configuration": {
            "context": settings.local_context,
            "output_tokens": settings.local_output_tokens,
            "embedding_model": settings.local_embedding_model,
        }
        if settings.ai_mode == "local"
        else None,
        "variants": {},
    }
    for reviewer in (False, True):
        fields = {f: [0, 0] for f in FIELDS}
        exact = 0
        parsed = 0
        tp = fp = fn = 0
        cites = valid_cites = supported_pairs = pairs = unsupported = imports = (
            parse_correct
        ) = 0
        latencies = []
        model_latencies = []
        tokens = (
            {"input_tokens": 0, "output_tokens": 0}
            if settings.ai_mode in ("vertex", "local")
            else None
        )
        cost = 0.0
        costs_available = True
        details = []
        failures = []
        with TestClient(app) as client:
            client.headers["Origin"] = "http://localhost:5173"
            login = client.post(
                "/api/login", json={"username": "evaluator", "password": password}
            )
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
            for case in selected:
                with DB() as db:
                    db.execute(delete(Customer))
                    db.commit()
                if case.parse_error:
                    response = client.post(
                        "/api/uploads", files={"file": ("case.csv", case.csv)}
                    )
                    parse_correct += response.status_code == 422
                    details.append(
                        {
                            "case": case.name,
                            "split": case.split,
                            "parse_rejection_correct": response.status_code == 422,
                        }
                    )
                    continue
                headers, rows = parse_csv(case.csv)
                parsed += 1
                call_started = time.monotonic()
                try:
                    with DB() as db:
                        prediction, run = await suggest_mapping(
                            db, headers, rows, reviewer=reviewer
                        )
                except Exception as exc:
                    from pydantic import ValidationError

                    failure = {
                        "case": case.name,
                        "split": case.split,
                        "failure_kind": "structured_output"
                        if isinstance(exc, ValidationError)
                        else "infrastructure_or_runtime",
                        "error_type": type(exc).__name__,
                        "duration_ms": round((time.monotonic() - call_started) * 1000),
                        "manual_import_attempted": False,
                    }
                    if isinstance(exc, ValidationError):
                        failure["validation_errors"] = [
                            {
                                "location": list(e["loc"]),
                                "type": e["type"],
                                "message": e["msg"],
                            }
                            for e in exc.errors()
                        ]
                    failures.append(failure)
                    details.append(failure)
                    for field in fields.values():
                        field[1] += 1
                    tokens = None
                    costs_available = False
                    continue
                predicted = comparable(prediction)
                gold = comparable(case.mapping)
                for f in FIELDS:
                    fields[f][1] += 1
                    fields[f][0] += predicted.get(f, {}).get("source") == gold.get(
                        f, {}
                    ).get("source")
                exact += predicted == gold
                latencies.append(run["duration_ms"])
                model_latencies.extend(call["duration_ms"] for call in run["calls"])
                if tokens and run["usage"] is None:
                    tokens = None
                if tokens:
                    for k in tokens:
                        tokens[k] += run["usage"][k]
                if run["estimated_cost_usd"] is None:
                    costs_available = False
                else:
                    cost += run["estimated_cost_usd"]
                evidence = {e["id"]: e for e in run["evidence"]}
                cites += run["citation_audit"]["proposed"]
                valid_cites += run["citation_audit"]["valid"]
                for rule in prediction.rules:
                    for source, target in rule.categories.items():
                        pairs += 1
                        # Independent semantic oracle for this tiny approved tier alias policy.
                        supported_pairs += (source, target) in {
                            ("starter", "basic"),
                            ("professional", "pro"),
                            ("business", "enterprise"),
                        } and any(
                            "04-approved-aliases.md" == evidence[c]["document"]
                            for c in rule.citations
                            if c in evidence
                        )
                unsupported += sum(
                    "citation is outside" in issue for issue in run["checks"]
                )
                issues = mapping_issues(prediction, headers)
                actual = validate_rows(rows, prediction, set())
                predicted_bad = {
                    r["row_number"] for r in actual["rows"] if not r["valid"]
                }
                if issues:
                    predicted_bad = {r["row_number"] for r in rows}
                gold_bad = set(case.errors)
                tp += len(predicted_bad & gold_bad)
                fp += len(predicted_bad - gold_bad)
                fn += len(gold_bad - predicted_bad)
                # Evaluate imports using ground-truth operator-selected mapping, not repaired AI output.
                response = client.post(
                    "/api/uploads", files={"file": ("evaluation.csv", case.csv)}
                )
                url = "/api/uploads/" + response.json()["id"]
                client.put(url + "/mapping", json=case.mapping.model_dump())
                validation = client.post(url + "/validate")
                if mapping_issues(case.mapping, headers):
                    correct = validation.status_code == 422
                else:
                    item = validation.json()
                    expected_valid = len(rows) - len(gold_bad)
                    if expected_valid:
                        approval = client.post(
                            url + "/approve",
                            json={
                                "version": item["version"],
                                "validation_hash": item["validation"]["hash"],
                                "policy": "valid_only",
                            },
                        ).json()
                        body = {
                            "approval_id": approval["approval"]["id"],
                            "idempotency_key": "eval-" + approval["approval"]["id"],
                        }
                        response = client.post(url + "/import", json=body)
                        repeated = client.post(url + "/import", json=body)
                        correct = (
                            response.status_code == 200
                            and response.json()["imported"] == expected_valid
                            and response.json() == repeated.json()
                        )
                    else:
                        correct = (
                            client.post(
                                url + "/approve",
                                json={
                                    "version": item["version"],
                                    "validation_hash": item["validation"]["hash"],
                                    "policy": "valid_only",
                                },
                            ).status_code
                            == 409
                        )
                imports += correct
                details.append(
                    {
                        "case": case.name,
                        "split": case.split,
                        "exact_mapping": predicted == gold,
                        "validation_tp": len(predicted_bad & gold_bad),
                        "validation_fp": len(predicted_bad - gold_bad),
                        "validation_fn": len(gold_bad - predicted_bad),
                        "manual_import_correct": correct,
                        "mapping": prediction.model_dump(),
                        "evidence": run["evidence"],
                        "checks": run["checks"],
                        "review": run["review"],
                        "usage": run["usage"],
                        "duration_ms": run["duration_ms"],
                        "calls": run["calls"],
                    }
                )
        results["variants"][
            "investigator_reviewer" if reviewer else "investigator_only"
        ] = {
            "parsed_cases": parsed,
            "failures": failures,
            "per_field_mapping_accuracy": {f: v[0] / v[1] for f, v in fields.items()},
            "exact_mapping_success_rate": exact / parsed,
            "validation_precision": tp / (tp + fp) if tp + fp else None,
            "validation_recall": tp / (tp + fn) if tp + fn else None,
            "validation_counts": {"tp": tp, "fp": fp, "fn": fn},
            "unsupported_transformation_proposals": 0
            if settings.ai_mode == "mock"
            else None,
            "accepted_unsupported_transformations": 0,
            "invalid_citation_warnings": unsupported,
            "citation_validity": valid_cites / cites if cites else None,
            "category_claim_evidence_support": supported_pairs / pairs
            if pairs
            else None,
            "manual_import_correctness": imports / parsed,
            "parse_rejections_correct": parse_correct,
            "mean_workflow_duration_ms": statistics.mean(latencies)
            if latencies
            else None,
            "mean_model_call_duration_ms": statistics.mean(model_latencies)
            if model_latencies
            else None,
            "model_tokens": tokens,
            "estimated_cost_usd": cost if costs_available else None,
            "cases": details,
        }
    results["limitations"] = [
        "Mock results measure fixtures only."
        if settings.ai_mode == "mock"
        else "Actual configured model calls; no model quality guarantees.",
        "Import correctness uses ground-truth manual mappings, with API approval and repeated execution.",
        "Evidence support oracle covers only the three documented tier aliases, not arbitrary semantic entailment.",
        "Typed output rejects unsupported transformations; invalid model output aborts evaluation rather than counting as success.",
        "Small synthetic cases cannot establish production reliability; held-out cases are included and labeled.",
    ]
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/evaluation.json")
    parser.add_argument(
        "--split", choices=["all", "development", "heldout"], default="all"
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--case", action="append", choices=[c.name for c in cases()], dest="names"
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    result = asyncio.run(evaluate(args.split, args.limit, args.names))
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "variants"}, indent=2))
    for key, value in result["variants"].items():
        print(
            key, json.dumps({k: v for k, v in value.items() if k != "cases"}, indent=2)
        )
