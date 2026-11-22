import asyncio
import hashlib
import json

import pytest

from app import agents
from app.categories import AliasPair, CategoryPlan, category_preview, policy_text
from app.config import settings
from app.domain import Mapping, Rule, parse_csv


def evidence():
    document = policy_text()
    return {
        "id": "current-policy",
        "title": "Approved aliases",
        "document": "04-approved-aliases.md",
        "hash": hashlib.sha256(document.encode()).hexdigest(),
        "text": document.strip(),
    }


def pair(before, after, citation="P1"):
    return AliasPair(before=before, after=after, evidence_id=citation)


@pytest.mark.parametrize(
    ("values", "source", "stale", "outcome"),
    [
        (["basic", ""], "membership_band", False, "no_noncanonical_values"),
        (["gold"], "membership_band", False, "no_documented_alias_evidence"),
        (["professional"], "membership_band", True, "no_documented_alias_evidence"),
        (["professional"], None, False, "no_category_source"),
    ],
)
def test_skip_records_reason_without_category_model(
    monkeypatch, values, source, stale, outcome
):
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    doc = evidence()
    if stale:
        doc["hash"] = "stale"
    retrievals = []

    def retrieve(*args):
        retrievals.append(args)
        return [doc]

    async def model(name, schema, instruction, payload):
        assert name == "MappingAgent"
        return agents.Proposal(
            mapping=Mapping(
                rules=[Rule(destination="subscription_tier", source=source)]
                if source
                else []
            )
        ), None

    monkeypatch.setattr(agents, "retrieve", retrieve)
    monkeypatch.setattr(agents, "adk_call", model)
    headers = ["membership_band"]
    rows = [
        {"values": {"membership_band": value}, "row_number": i}
        for i, value in enumerate(values, 2)
    ]
    mapping, run = asyncio.run(
        agents.suggest_mapping(None, headers, rows, category_strategy="agent")
    )
    assert run["category"]["reason"] == outcome
    assert [c["agent"] for c in run["calls"]] == ["MappingAgent"]
    assert len(retrievals) == (2 if outcome == "no_documented_alias_evidence" else 1)
    preview = category_preview(mapping, headers, rows, set(), run["evidence"])
    assert preview["unresolved_rows"] == (
        1 if outcome == "no_documented_alias_evidence" else 0
    )


def test_profile_privacy_exact_policy_and_one_refinement(monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    doc = evidence()
    monkeypatch.setattr(agents, "retrieve", lambda *args: [doc])
    headers, rows = parse_csv(
        b"name,email,joined,membership_band\n"
        b"Person,private@example.com,03/04/2026,basic\n"
        b"Other,other@example.com,03/04/2026,professional\n"
        b"Third,third@example.com,03/04/2026,professional\n"
        b"Fourth,fourth@example.com,03/04/2026, starter \n"
        b"Fifth,fifth@example.com,03/04/2026,sensitive@example.com\n"
        b"Sixth,sixth@example.com,03/04/2026,\n"
    )
    calls = []

    async def model(name, schema, instruction, payload):
        calls.append(name)
        if name == "MappingAgent":
            return agents.Proposal(
                mapping=Mapping(
                    rules=[
                        Rule(destination="name", source="name"),
                        Rule(destination="email", source="email"),
                        Rule(
                            destination="signup_date",
                            source="joined",
                            date_format="%m/%d/%Y",
                        ),
                        Rule(
                            destination="subscription_tier",
                            source="membership_band",
                            categories={"starter": "pro"},
                        ),
                    ]
                )
            ), None
        serialized = json.dumps(payload)
        assert "example.com" not in serialized and "03/04/2026" not in serialized
        assert payload["source_column"] == "membership_band"
        assert payload["recognized_rows"] == payload["blank_rows"] == 1
        assert payload["omitted_distinct"] == 1
        assert payload["eligible_values"] == [
            {"value": "professional", "rows": 2},
            {"value": "starter", "rows": 1},
        ]
        if "preview_feedback" not in payload:
            return CategoryPlan(
                pairs=[
                    pair("professional", "pro"),
                    pair("starter", "pro"),
                    pair("starter", "basic"),
                    pair("sensitive@example.com", "pro"),
                    pair("absent", "pro"),
                ],
                unresolved=[],
            ), None
        assert payload["preview_feedback"]["accepted"][0]["affected_rows"] == 2
        return CategoryPlan(
            pairs=[pair("starter", "basic", "wrong-chunk")], unresolved=["starter"]
        ), None

    monkeypatch.setattr(agents, "adk_call", model)
    mapping, run = asyncio.run(
        agents.suggest_mapping(None, headers, rows, category_strategy="agent")
    )
    assert calls == [
        "MappingAgent",
        "CategoryTransformationAgent",
        "CategoryTransformationAgent",
    ]
    assert run["revision_count"] == 1 and run["category"]["rejected_proposals"] == 5
    assert run["category"]["model_unresolved"] == ["starter"]
    assert mapping.rules[-1].categories == {"professional": "pro"}
    preview = category_preview(mapping, headers, rows, set(), run["evidence"])
    assert preview["affected_rows"] == 2
    assert preview["rules"][0]["evidence_id"] == "current-policy"
    assert preview["unresolved_distinct"] == 2 and preview["unresolved_rows"] == 2
    assert preview["incomplete_validation"] == [
        "Select an explicit date format for signup_date"
    ]
    assert {f["id"] for f in preview["findings"]} == {
        "mapping.signup_date.format",
        "rows.subscription_tier",
    }


def test_invalid_agent_output_preserves_mapping(monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    monkeypatch.setattr(agents, "retrieve", lambda *args: [evidence()])

    async def model(name, schema, instruction, payload):
        if name == "MappingAgent":
            return agents.Proposal(
                mapping=Mapping(
                    rules=[
                        Rule(destination="subscription_tier", source="tier"),
                    ]
                )
            ), None
        return schema.model_validate_json(
            '{"pairs": [], "unresolved": [], "source_column":"email"}'
        ), None

    monkeypatch.setattr(agents, "adk_call", model)
    headers, rows = parse_csv(b"tier\nprofessional\n")
    mapping, run = asyncio.run(
        agents.suggest_mapping(None, headers, rows, category_strategy="agent")
    )
    assert mapping.rules[0].source == "tier" and not mapping.rules[0].categories
    assert run["category"]["status"] == "failed"
    assert run["calls"][-1]["error_type"] == "ValidationError"


def test_preview_is_read_only_and_category_edit_invalidates_approval(client):
    upload = client.post(
        "/api/uploads",
        files={
            "file": (
                "tiers.csv",
                b"name,email,signup_date,plan\n"
                b"Example,first@example.com,2026-04-03,professional\n"
                b"Example,second@example.com,2026-04-03,pro\n",
                "text/csv",
            )
        },
    ).json()
    url = "/api/uploads/" + upload["id"]
    item = client.post(url + "/suggest").json()
    assert item["agent_run"]["review"] is None
    assert item["agent_run"]["category"]["reason"] == "mock_documented_lookup"
    validation = client.post(url + "/validate").json()["validation"]
    approved = client.post(
        url + "/approve",
        json={
            "version": item["version"],
            "validation_hash": validation["hash"],
            "policy": "valid_only",
        },
    ).json()
    spec = approved["mapping"]
    tier = next(r for r in spec["rules"] if r["destination"] == "subscription_tier")
    tier["categories"] = {"professional": "enterprise", "absent": "basic"}
    preview = client.post(url + "/category-preview", json=spec).json()
    assert preview["affected_rows"] == 0
    assert preview["unresolved"] == [{"value": "professional", "rows": 1}]
    assert {r["reason"] for r in preview["rejected_rules"]} == {
        "pair_not_supported_by_citation",
        "source_value_absent",
    }
    current = client.get(url).json()
    assert current["approval"] == approved["approval"]
    assert current["validation"] == validation and current["version"] == item["version"]
    changed = client.put(url + "/mapping", json=spec).json()
    assert changed["version"] == item["version"] + 1
    assert changed["approval"] is None and changed["validation"] is None
    stale = client.post(
        url + "/import",
        json={
            "approval_id": approved["approval"]["id"],
            "idempotency_key": "old-tier-approval",
        },
    )
    assert stale.status_code == 409
