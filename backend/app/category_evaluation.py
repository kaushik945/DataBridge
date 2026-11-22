"""Opt-in, read-only development comparison of the category workflows."""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from sqlalchemy import text

from .agents import (
    CATEGORY_INSTRUCTION,
    MAPPING_INSTRUCTION,
    MAPPING_QUERY,
    Proposal,
    adk_call,
    category_context,
    category_payload,
    mapping_payload,
    propose_categories,
    require_human_slash_format,
    suggest_mapping,
)
from .categories import (
    CategoryPlan,
    approved_pairs,
    category_preview,
    make_handoff,
    policy_text,
    profile_column,
    tier_rule,
)
from .config import settings
from .domain import FIELDS, Mapping, Rule, parse_csv
from .models import DB
from .retrieval import retrieve

# Independent expected pairs. The final two cases deliberately expect abstention.
CASES = [
    (
        "unfamiliar",
        "membership_band",
        ("basic", "professional", "gold", " professional "),
        {"professional": "pro"},
    ),
    (
        "three_aliases",
        "plan",
        ("starter", "professional", "business"),
        {"starter": "basic", "professional": "pro", "business": "enterprise"},
    ),
    (
        "case_sensitive",
        "package",
        ("Starter", "starter", "", "pro"),
        {"starter": "basic"},
    ),
    ("canonical", "membership_band", ("basic", "pro", "enterprise"), {}),
    ("unsupported", "plan", ("premium", "gold", "basic"), {}),
]
VARIANTS = ("lookup", "single", "two_agents")
FRESH_VARIANTS = ("two_agents", "lookup", "profile_lookup")
LOOKUP_VARIANTS = ("lookup", "profile_lookup")


@dataclass(frozen=True)
class SourceCase:
    name: str
    columns: dict[str, tuple[str, ...]]
    expected_source: str | None
    expected_pairs: dict[str, str]

    def input(self):
        # All cases map the same real customer fields. Category roles are labeled independently.
        size = len(next(iter(self.columns.values())))
        base = [
            ("name", ["Example"] * size),
            ("email", [f"fresh{i}@example.com" for i in range(size)]),
            ("joined", ["03/04/2026"] * size),
            ("country", ["FR"] * size),
        ]
        headers = [header for header, _ in base] + list(self.columns)
        columns = [values for _, values in base] + list(self.columns.values())
        csv = "\n".join(
            [
                ",".join(headers),
                *(",".join(values) for values in zip(*columns, strict=True)),
            ]
        )
        headers, rows = parse_csv(csv.encode())
        expected_sources = {
            "name": "name",
            "email": "email",
            "signup_date": "joined",
            "country_code": "country",
            "subscription_tier": self.expected_source,
        }
        return headers, rows, expected_sources


# Label source choices and explicit abstentions before model execution.
FRESH_CASES = (
    SourceCase(
        "billing_plan_decoy",
        {
            "plan": ("annual", "monthly", "quarterly"),
            "benefit_code": ("basic", "pro", "professional"),
        },
        "benefit_code",
        {"professional": "pro"},
    ),
    SourceCase(
        "misleading_band",
        {
            "membership_band": ("north", "west", "south"),
            "bundle_level": ("starter", "professional", "business"),
        },
        "bundle_level",
        {"starter": "basic", "professional": "pro", "business": "enterprise"},
    ),
    SourceCase(
        "competing_clear",
        {
            "tier": ("gold", "basic", "silver", "premium"),
            "plan": ("basic", "professional", "pro", "starter"),
        },
        "plan",
        {"professional": "pro", "starter": "basic"},
    ),
    SourceCase(
        "competing_close",
        {
            "tier": ("basic", "pro", "starter", "mystery", "enterprise"),
            "membership_band": ("basic", "pro", "basic", "basic", "enterprise"),
        },
        None,
        {},
    ),
    SourceCase(
        "competing_equal",
        {
            "tier": ("basic", "pro", "enterprise"),
            "package": ("business", "starter", "professional"),
        },
        None,
        {},
    ),
    SourceCase(
        "weak_coverage",
        {
            "tier": ("gold", "rare", "manual", "pro"),
            "fee_code": ("a", "b", "c", "d"),
        },
        None,
        {},
    ),
    SourceCase(
        "canonical_control",
        {
            "plan": ("basic", "pro", "enterprise"),
        },
        "plan",
        {},
    ),
    SourceCase(
        "unfamiliar_control",
        {
            "access_level": ("pro", "starter", "enterprise", "professional"),
        },
        "access_level",
        {"starter": "basic", "professional": "pro"},
    ),
)


HOLDOUT_CASES = (
    SourceCase(
        "invoice_cycle_decoy",
        {
            "subscription_tier": ("quarterly", "monthly", "annual"),
            "service_level": ("pro", "business", "enterprise"),
        },
        "service_level",
        {"business": "enterprise"},
    ),
    SourceCase(
        "package_label_competition",
        {
            "package": ("gold", "basic", "trial", "custom"),
            "loyalty_band": ("professional", "basic", "enterprise", "starter"),
        },
        "loyalty_band",
        {"professional": "pro", "starter": "basic"},
    ),
    SourceCase(
        "equally_plausible_catalogs",
        {
            "product_tier": ("basic", "pro", "enterprise"),
            "service_band": ("starter", "professional", "business"),
        },
        None,
        {},
    ),
    SourceCase(
        "canonical_entitlements",
        {"entitlement_code": ("basic", "enterprise", "pro", "pro")},
        "entitlement_code",
        {},
    ),
    SourceCase(
        "weak_catalog_evidence",
        {"catalog_level": ("pilot", "contract", "pro", "paused")},
        None,
        {},
    ),
)


class CombinedProposal(Proposal):
    category_plan: CategoryPlan


def csv_case(source, values):
    return parse_csv(
        (
            f"name,email,joined,{source}\n"
            + "".join(
                f"Example,p{i}@example.com,03/04/2026,{value}\n"
                for i, value in enumerate(values)
            )
        ).encode()
    )


async def single_agent(db, headers, rows):
    """One generalist gets the same policy and candidate-column profiles upfront."""
    db.execute(text("SELECT pg_advisory_xact_lock(827301)"))
    evidence = retrieve(db, MAPPING_QUERY + " ".join(headers), 8)[:4]
    authority = {value for value, _ in approved_pairs(policy_text())}
    profiles = [
        (rule, profile_column(rows, rule))
        for header in headers
        for rule in [Rule(destination="subscription_tier", source=header)]
    ]
    candidates = [
        (rule, counts) for rule, counts in profiles if counts.keys() & authority
    ]
    policy = []
    support = {}
    if candidates:
        context, support = category_context(db, *candidates[0])
        policy = context.evidence
    handoffs = {
        rule.source: (make_handoff(rule, counts, policy, support), counts)
        for rule, counts in candidates
    }
    payload = mapping_payload(headers, rows, evidence)
    short_policy, _ = (
        category_payload(next(iter(handoffs.values()))[0])
        if handoffs
        else ({"evidence": []}, {})
    )
    payload["category_evidence"] = short_policy["evidence"]
    payload["category_profiles"] = [
        context.model_dump(exclude={"evidence"}) for context, _ in handoffs.values()
    ]
    calls = []
    alias_audit = []

    async def call(name, schema, instruction, data):
        entry = {"agent": name, "input": {"payload": data}}
        calls.append(entry)
        start = time.monotonic()
        try:
            result, usage = await asyncio.wait_for(
                adk_call(name, schema, instruction, data),
                timeout=settings.local_timeout_seconds,
            )
            entry["model_output"] = result.model_dump()
            return result, usage
        except Exception as exc:
            entry["error_type"] = type(exc).__name__
            raise
        finally:
            entry["duration_ms"] = round((time.monotonic() - start) * 1000)

    instruction = (
        MAPPING_INSTRUCTION.replace(
            "Leave categories empty; category transformations are a separate task.",
            "Keep mapping.rules categories empty. Put tier alias pairs in category_plan.",
        )
        + " As the same agent, propose alias pairs using only the profile for the source you selected. "
        "Copy policy references from category_evidence. With no eligible profile, return an empty category_plan. "
        + CATEGORY_INSTRUCTION.replace(
            "You are the Category Transformation Agent for subscription_tier. ", ""
        )
    )
    try:
        proposal, _ = await call("MappingAgent", CombinedProposal, instruction, payload)
    except Exception as exc:
        return (
            Mapping(rules=[]),
            evidence + policy,
            calls,
            alias_audit,
            type(exc).__name__,
        )

    require_human_slash_format(proposal, rows)
    for rule in proposal.mapping.rules:
        rule.categories = {}
    tier = tier_rule(proposal.mapping)
    if tier is None or tier.source not in handoffs:
        alias_audit.extend(
            {
                "attempt": 1,
                **pair.model_dump(),
                "reason": "no_eligible_profile_for_source",
            }
            for pair in proposal.category_plan.pairs
        )
        return (
            proposal.mapping,
            evidence + policy,
            calls,
            alias_audit,
            None,
        )
    context, counts = handoffs[tier.source]
    attempts = []
    pairs, result = await propose_categories(
        context,
        counts,
        support,
        call,
        "MappingAgent",
        "As the Mapping Agent, refine only your category plan. "
        + CATEGORY_INSTRUCTION.replace(
            "You are the Category Transformation Agent for subscription_tier. ", ""
        ),
        initial=proposal.category_plan,
        audit=attempts,
    )
    alias_audit.extend(
        {"attempt": attempt["attempt"], **rejection}
        for attempt in attempts
        for rejection in attempt["rejected"]
    )
    tier.categories = {p.before: p.after for p in pairs}
    tier.citations = sorted({p.evidence_id for p in pairs})
    return (
        proposal.mapping,
        evidence + policy,
        calls,
        alias_audit,
        result["reason"],
    )


def source_columns(rules):
    return {rule["destination"]: rule["source"] for rule in rules}


def discarded_mapping_pairs(calls):
    """All workflows forbid alias pairs in the column mapping response."""
    return [
        {
            "call": index,
            "field": rule["destination"],
            "before": before,
            "after": after,
            "reason": "pairs_in_mapping_output",
        }
        for index, call in enumerate(calls, 1)
        for rule in call.get("model_output", {}).get("mapping", {}).get("rules", [])
        for before, after in rule["categories"].items()
    ]


def score_sources(expected, selected):
    """One explicit label and comparison per destination, including omission."""
    return [
        {
            "destination": field,
            "expected": expected.get(field),
            "selected": selected.get(field),
            "reason": "unexpected_assignment"
            if expected.get(field) is None
            else "missing_assignment"
            if selected.get(field) is None
            else "wrong_source",
        }
        for field in FIELDS
        if expected.get(field) != selected.get(field)
    ]


def call_summary(call):
    payload = call["input"]["payload"]
    output = call.get("model_output", {})
    return {
        "agent": call["agent"],
        "duration_ms": call["duration_ms"],
        "mapping_sources": source_columns(output["mapping"]["rules"])
        if "mapping" in output
        else None,
        "category_output": output.get(
            "category_plan", output if "pairs" in output else None
        ),
        "candidate_profiles": payload.get(
            "category_profiles", payload.get("tier_source_profile")
        ),
        "preview_feedback": payload.get("preview_feedback"),
        "error_type": call.get("error_type"),
    }


async def evaluate_case(db, variant, case):
    if isinstance(case, SourceCase):
        name, source, expected = case.name, case.expected_source, case.expected_pairs
        headers, rows, expected_sources = case.input()
    else:
        name, source, values, expected = case
        headers, rows = csv_case(source, values)
        expected_sources = {
            "name": "name",
            "email": "email",
            "signup_date": "joined",
            "subscription_tier": source,
            "country_code": None,
        }
    start = time.monotonic()
    error = None
    alias_audit = []
    category_outcome = None
    if variant == "single":
        mapping, evidence, calls, alias_audit, error = await single_agent(
            db, headers, rows
        )
        rejected = len(alias_audit)
        category_ms = None
    else:
        try:
            mapping, run = await suggest_mapping(
                db,
                headers,
                rows,
                category_strategy="agent" if variant == "two_agents" else variant,
            )
            evidence = run["evidence"]
            calls = run["calls"]
            category_outcome = run["category"]
            rejected = run["category"]["rejected_proposals"]
            category_ms = run["timings"]["category_ms"]
            if run["category"]["status"] == "failed":
                error = run["category"]["reason"]
        except Exception as exc:
            mapping, evidence, rejected, category_ms = Mapping(rules=[]), [], 0, None
            calls = getattr(exc, "agent_calls", [])
            error = type(exc).__name__
    mapping_rejections = discarded_mapping_pairs(calls)
    rejected += len(mapping_rejections)
    alias_audit = mapping_rejections + alias_audit
    preview = category_preview(mapping, headers, rows, set(), evidence)
    actual = {(p["before"], p["after"]) for p in preview["rules"]}
    wanted = set(expected.items())
    sources = {r.destination: r.source for r in mapping.rules}
    trace = [call_summary(call) for call in calls]
    initial_sources = trace[0]["mapping_sources"] if trace else None
    source_differences = score_sources(expected_sources, sources)
    correct = len(actual & wanted) if preview["source_column"] == source else 0
    pair_edits = (
        len(actual ^ wanted) if preview["source_column"] == source else len(wanted)
    )
    return {
        "case": name,
        "variant": variant,
        "expected_pairs": expected,
        "tier_source": preview["source_column"],
        "accepted_pairs": dict(sorted(actual)),
        "correct": correct,
        "python_rejections": rejected,
        "mapping_output_rejections": len(mapping_rejections),
        "pair_edits": pair_edits,
        "source_edits": len(source_differences),
        "tier_source_correct": preview["source_column"] == source,
        "expected_sources": {field: expected_sources.get(field) for field in FIELDS},
        "initial_sources": initial_sources,
        "final_sources": {field: sources.get(field) for field in FIELDS},
        "source_differences": source_differences,
        "preview_feedback": [
            c["preview_feedback"] for c in trace if c["preview_feedback"] is not None
        ],
        "alias_rejection_audit": alias_audit,
        "category_outcome": category_outcome,
        "calls": trace,
        "affected_rows": preview["affected_rows"],
        "unresolved_rows": preview["unresolved_rows"],
        "model_calls": len(calls),
        "workflow_ms": round((time.monotonic() - start) * 1000, 3),
        "category_stage_ms": category_ms,
        "failure": error,
    }


async def evaluate(suite, variants=None):
    cases, defaults = {
        "known": (CASES, VARIANTS),
        "fresh": (FRESH_CASES, FRESH_VARIANTS),
        "holdout": (HOLDOUT_CASES, LOOKUP_VARIANTS),
    }[suite]
    variants = tuple(dict.fromkeys(variants or defaults))
    # Warm up model, application imports and embeddings using a separate file.
    with DB() as db:
        await evaluate_case(
            db,
            "profile_lookup",
            ("warmup", "tier", ("business", "pro"), {"business": "enterprise"}),
        )
    records = []
    for index, case in enumerate(cases):
        shift = index % len(variants)
        for variant in variants[shift:] + variants[:shift]:
            with DB() as db:
                result = await evaluate_case(db, variant, case)
            records.append(result)
            print(f"{result['case']}: {variant} completed", flush=True)
    summary = {}
    for variant in variants:
        subset = [r for r in records if r["variant"] == variant]
        summary[variant] = {
            **{
                key: sum(r[key] for r in subset)
                for key in (
                    "correct",
                    "python_rejections",
                    "pair_edits",
                    "source_edits",
                    "tier_source_correct",
                    "model_calls",
                )
            },
            "expected": sum(len(r["expected_pairs"]) for r in subset),
            "failures": sum(r["failure"] is not None for r in subset),
            "median_workflow_ms": median(r["workflow_ms"] for r in subset),
            "total_workflow_ms": round(sum(r["workflow_ms"] for r in subset), 3),
        }
    return {
        "model": settings.local_model,
        "suite": suite,
        "context": settings.local_context,
        "output_cap": settings.local_output_tokens,
        "temperature": 0,
        "thinking": False,
        "rows": records,
        "summary": summary,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--suite", choices=("known", "fresh", "holdout"), default="known"
    )
    parser.add_argument("--variants", nargs="+", choices=(*VARIANTS, "profile_lookup"))
    args = parser.parse_args()
    if settings.ai_mode != "local":
        raise SystemExit("Set AI_MODE=local and ingest policy documents before running")
    result = asyncio.run(evaluate(args.suite, args.variants))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
