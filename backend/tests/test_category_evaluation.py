import asyncio

import pytest

from app import agents
from app.category_evaluation import (
    FRESH_CASES,
    HOLDOUT_CASES,
    discarded_mapping_pairs,
    score_sources,
)
from app.categories import PROFILE_LIMIT, profile_tier_sources
from app.config import settings
from app.domain import Mapping, Rule


def test_source_score_distinguishes_wrong_missing_and_extra_assignments():
    expected = {"name": "name", "email": "email", "subscription_tier": "plan"}
    actual = {"name": "phone", "email": "email", "country_code": "plan"}
    assert score_sources(expected, actual) == [
        {
            "destination": "name",
            "expected": "name",
            "selected": "phone",
            "reason": "wrong_source",
        },
        {
            "destination": "subscription_tier",
            "expected": "plan",
            "selected": None,
            "reason": "missing_assignment",
        },
        {
            "destination": "country_code",
            "expected": None,
            "selected": "plan",
            "reason": "unexpected_assignment",
        },
    ]


def test_alias_rejection_scoring_includes_out_of_scope_mapping_pairs():
    rule = Rule(
        destination="subscription_tier", source="tier", categories={"starter": "basic"}
    )
    proposal = {"mapping": Mapping(rules=[rule]).model_dump()}
    active = {"model_output": proposal}
    single = {"model_output": {**proposal, "category_plan": {"pairs": []}}}
    assert (
        discarded_mapping_pairs([active])
        == discarded_mapping_pairs([single])
        == [
            {
                "call": 1,
                "field": "subscription_tier",
                "before": "starter",
                "after": "basic",
                "reason": "pairs_in_mapping_output",
            }
        ]
    )


@pytest.mark.parametrize(
    "case", FRESH_CASES + HOLDOUT_CASES, ids=lambda case: case.name
)
def test_profiles_leave_ties_and_weak_columns_for_review(case):
    headers, rows, _ = case.input()
    profile = profile_tier_sources(headers, rows)
    assert profile["strong_candidate"] == case.expected_source
    assert profile["abstain_reason"] == {
        "competing_close": "competing_coverage",
        "competing_equal": "competing_coverage",
        "weak_coverage": "weak_coverage",
        "equally_plausible_catalogs": "competing_coverage",
        "weak_catalog_evidence": "weak_coverage",
    }.get(case.name)
    assert all(
        set(column)
        == {"source", "canonical_rows", "documented_alias_rows", "supported_rows"}
        for column in profile["candidates"]
    )


def test_profile_bounds_the_payload_and_retains_zero_coverage_when_it_fits():
    headers, rows, _ = FRESH_CASES[0].input()
    profile = profile_tier_sources(headers, rows)
    assert (
        next(c for c in profile["candidates"] if c["source"] == "plan")[
            "supported_rows"
        ]
        == 0
    )
    for i in range(PROFILE_LIMIT):
        col = f"ignored{i}"
        headers.append(col)
        for row in rows:
            row["values"][col] = "free text"
    profile = profile_tier_sources(headers, rows)
    assert len(profile["candidates"]) == PROFILE_LIMIT and profile["truncated"]
    assert profile["strong_candidate"] == "benefit_code"
    assert "free text" not in str(profile)


def test_profile_lookup_rejects_unsupported_source_without_retry(monkeypatch):
    headers, rows, _ = FRESH_CASES[0].input()
    profile = profile_tier_sources(headers, rows)
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    monkeypatch.setattr(agents, "retrieve", lambda *args: [])
    calls = []

    async def model(name, schema, instruction, payload):
        calls.append(name)
        assert payload["tier_source_profile"] == profile
        assert instruction.startswith(agents.MAPPING_INSTRUCTION)
        return agents.Proposal(
            mapping=Mapping(
                rules=[Rule(destination="subscription_tier", source="plan")]
            )
        ), None

    monkeypatch.setattr(agents, "adk_call", model)
    mapping, run = asyncio.run(
        agents.suggest_mapping(
            None,
            headers,
            rows,
            category_strategy="profile_lookup",
        )
    )
    assert calls == ["MappingAgent"]
    assert mapping.rules == []
    assert run["calls"][0]["model_output"]["mapping"]["rules"][0]["source"] == "plan"
    assert run["category"]["reason"] == "no_category_source"
    assert run["category"]["source_review_reason"] == "model_disagreed_with_profile"


@pytest.mark.parametrize("case", FRESH_CASES, ids=lambda case: case.name)
def test_normal_upload_uses_profiled_lookup(client, case):
    assert settings.tier_mapping_strategy == "profile_lookup"
    headers, rows, _ = case.input()
    content = "\n".join(
        [
            ",".join(headers),
            *(",".join(row["values"][h] for h in headers) for row in rows),
        ]
    )
    upload = client.post("/api/uploads", files={"file": ("tier.csv", content)}).json()
    suggested = client.post(f"/api/uploads/{upload['id']}/suggest")
    assert suggested.status_code == 200, suggested.text
    item = suggested.json()
    category = item["agent_run"]["category"]
    assert category["strategy"] == "profile_lookup"
    assert category["source_column"] == case.expected_source
    tier = next(
        (
            r
            for r in item["mapping"]["rules"]
            if r["destination"] == "subscription_tier"
        ),
        None,
    )
    if case.expected_source is None:
        assert tier is None
        assert category["source_review_reason"] in (
            "weak_coverage",
            "competing_coverage",
        )
    else:
        assert tier["source"] == case.expected_source
        assert tier["categories"] == case.expected_pairs
