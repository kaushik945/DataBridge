"""Policy-backed tier proposals and read-only previews."""

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .domain import TIERS, Mapping, mapping_issues, source_value
from .review import validator_results

CATEGORY_FIELD = "subscription_tier"
POLICY_DOCUMENT = "04-approved-aliases.md"
PROFILE_LIMIT = 12


class AliasPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: str = Field(min_length=1, max_length=80)
    after: str = Field(min_length=1, max_length=80)
    evidence_id: str = Field(min_length=1, max_length=80)


class CategoryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: list[AliasPair] = Field(max_length=PROFILE_LIMIT)
    unresolved: list[str] = Field(max_length=PROFILE_LIMIT)


class CategoryValue(BaseModel):
    value: str
    rows: int


class CategoryHandoff(BaseModel):
    source_column: str
    allowed_values: tuple[str, ...] = TIERS
    recognized_rows: int
    blank_rows: int
    noncanonical_distinct: int
    noncanonical_rows: int
    eligible_values: list[CategoryValue]
    truncated: bool
    omitted_distinct: int
    evidence: list[dict]


def tier_rule(mapping):
    return next((r for r in mapping.rules if r.destination == CATEGORY_FIELD), None)


def profile_column(rows, rule):
    return Counter(source_value(row, rule) for row in rows) if rule else Counter()


def policy_text():
    root = Path(__file__).resolve().parents[1]
    packaged = root / "knowledge" / POLICY_DOCUMENT
    source = root.parent / "docs" / "knowledge" / POLICY_DOCUMENT
    return (packaged if packaged.is_file() else source).read_text(encoding="utf-8")


def approved_pairs(document: str) -> set[tuple[str, str]]:
    """Parse the explicit, semicolon-separated approval statement only."""
    statement = re.search(
        r"approves these explicit source-to-target pairs: ([^.]+)\.", document
    )
    if not statement:
        return set()
    pairs = set()
    for pair in statement[1].split(";"):
        match = re.fullmatch(
            r"\s*([a-z][a-z0-9_-]*)\s*\u2192\s*([a-z][a-z0-9_-]*)\s*", pair
        )
        if match and match[2] in TIERS and match[1] not in TIERS:
            pairs.add((match[1], match[2]))
    return pairs


def profile_tier_sources(headers, rows):
    """Rank every column by exact tier coverage and bound the model payload."""
    approved = approved_pairs(policy_text())
    targets_per_alias = Counter(before for before, _ in approved)
    aliases = {before for before, count in targets_per_alias.items() if count == 1}
    candidates = []
    for header in headers:
        canonical_rows = alias_rows = 0
        for row in rows:
            value = row["values"][header].strip()
            canonical_rows += value in TIERS
            alias_rows += value in aliases
        candidates.append(
            {
                "source": header,
                "canonical_rows": canonical_rows,
                "documented_alias_rows": alias_rows,
                "supported_rows": canonical_rows + alias_rows,
            }
        )
    ranked = sorted(candidates, key=lambda candidate: -candidate["supported_rows"])
    first = ranked[0]["supported_rows"] if ranked else 0
    second = ranked[1]["supported_rows"] if len(ranked) > 1 else 0
    if first < 2 or first * 3 < len(rows) * 2:
        reason = "weak_coverage"
    elif first == second or (first - second) * 4 < len(rows):
        reason = "competing_coverage"
    else:
        reason = None
    return {
        "total_rows": len(rows),
        # Include zero-coverage columns when space permits. Omission of a column
        # from this bounded list is never eligibility to propose it.
        "candidates": ranked[:PROFILE_LIMIT],
        "truncated": len(ranked) > PROFILE_LIMIT,
        "strong_candidate": ranked[0]["source"] if reason is None else None,
        "abstain_reason": reason,
    }


def policy_support(evidence):
    """Require both the current source document and the cited chunk to say the pair."""
    if not any(e["document"] == POLICY_DOCUMENT for e in evidence):
        return {}
    document = policy_text()
    version = hashlib.sha256(document.encode()).hexdigest()
    authority = approved_pairs(document)
    support = defaultdict(set)
    for chunk in evidence:
        if (
            chunk["document"] == POLICY_DOCUMENT
            and chunk["hash"] == version
            and chunk["text"] in document
        ):
            for before, after in authority & approved_pairs(chunk["text"]):
                support[before, after].add(chunk["id"])
    return dict(support)


def make_handoff(rule, counts, evidence, support):
    noncanonical = {v: n for v, n in counts.items() if v and v not in TIERS}
    # Export only policy-vetted category tokens. Unknown values may contain PII
    # or free text even when a model has picked a plausible category header.
    documented = sorted({before for before, _ in support} & noncanonical.keys())
    eligible = documented[:PROFILE_LIMIT]
    policy_ids = {citation for ids in support.values() for citation in ids}
    return CategoryHandoff(
        source_column=rule.source,
        recognized_rows=sum(counts[v] for v in TIERS),
        blank_rows=counts[""],
        noncanonical_distinct=len(noncanonical),
        noncanonical_rows=sum(noncanonical.values()),
        eligible_values=[CategoryValue(value=v, rows=counts[v]) for v in eligible],
        truncated=len(documented) > len(eligible),
        omitted_distinct=len(noncanonical) - len(eligible),
        evidence=[e for e in evidence if e["id"] in policy_ids],
    )


def lookup_pairs(counts, support):
    targets = defaultdict(set)
    for before, after in support:
        if counts[before]:
            targets[before].add(after)
    return [
        AliasPair(before=before, after=after, evidence_id=min(support[before, after]))
        for before, choices in sorted(targets.items())
        if len(choices) == 1
        for after in sorted(choices)
    ][:PROFILE_LIMIT]


def check_pairs(pairs, counts, support):
    proposed = defaultdict(set)
    documented = defaultdict(set)
    for before, after in support:
        documented[before].add(after)
    for pair in pairs:
        proposed[pair.before].add(pair.after)
    accepted = {}
    rejected = []
    for pair in pairs:
        before, after = pair.before, pair.after
        if len(proposed[before]) > 1 or len(documented[before]) > 1:
            reason = "conflicting_targets"
        elif not counts[before]:
            reason = "source_value_absent"
        elif after not in TIERS:
            reason = "target_not_allowed"
        elif pair.evidence_id not in support.get((before, after), ()):
            reason = "pair_not_supported_by_citation"
        else:
            accepted[before] = pair
            continue
        rejected.append({"value": before, "reason": reason})
    return list(accepted.values()), rejected


def category_preview(mapping: Mapping, headers, rows, existing, evidence):
    rule = tier_rule(mapping)
    counts = (
        profile_column(rows, rule) if rule and rule.source in headers else Counter()
    )
    support = policy_support(evidence)
    candidates = []
    if rule:
        for before, after in rule.categories.items():
            citations = support.get((before, after), set()).intersection(rule.citations)
            candidates.append(
                AliasPair.model_construct(
                    before=before, after=after, evidence_id=min(citations, default="")
                )
            )
    accepted, rejected = check_pairs(candidates, counts, support)
    covered = {p.before for p in accepted}
    preview_mapping = mapping.model_copy(deep=True)
    preview_rule = tier_rule(preview_mapping)
    if preview_rule:
        preview_rule.categories = {p.before: p.after for p in accepted}
    unresolved = sorted(
        (
            (value, count)
            for value, count in counts.items()
            if value and value not in TIERS and value not in covered
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return {
        "source_column": rule.source if rule else None,
        "recognized_rows": sum(counts[v] for v in TIERS),
        "blank_rows": counts[""],
        "rules": [
            {**pair.model_dump(), "affected_rows": counts[pair.before]}
            for pair in accepted
        ],
        "affected_rows": sum(counts[p.before] for p in accepted),
        "unresolved": [
            {"value": value[:80] + ("..." if len(value) > 80 else ""), "rows": count}
            for value, count in unresolved[:PROFILE_LIMIT]
        ],
        "unresolved_distinct": len(unresolved),
        "unresolved_rows": sum(count for _, count in unresolved),
        "unresolved_truncated": len(unresolved) > PROFILE_LIMIT,
        "rejected_rules": rejected,
        "incomplete_validation": mapping_issues(preview_mapping, headers),
        "findings": [
            f
            for f in validator_results(preview_mapping, headers, rows, existing)
            if f["status"] != "pass"
        ],
    }
