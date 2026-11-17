"""Evaluation mechanics and date contracts, without local inference."""

from app.agents import Proposal, grounded_proposal_schema, require_human_slash_format
from app.assessment import baseline, mapping_score, sha, source_rows
from app.assessment_cases import assessment_cases
from app.domain import Mapping, Rule, schema_facts, validate_rows


def test_date_null_is_explicit_and_both_compliant_and_guessed_outputs_are_safe():
    schema = grounded_proposal_schema(["joined"], [{"id": "policy"}])
    assert "human date selection required" in str(schema.model_json_schema())
    assert schema_facts()["fields"]["signup_date"]["unresolved_date_format"] is None
    for guess in (None, "%d/%m/%Y"):
        proposal = Proposal(
            mapping=Mapping(
                rules=[
                    Rule(destination="signup_date", source="joined", date_format=guess)
                ]
            )
        )
        require_human_slash_format(proposal, [{"values": {"joined": "13/04/2026"}}])
        assert proposal.mapping.rules[0].date_format is None


def test_baseline_abstains_for_competing_aliases_and_observes_all_date_rows():
    cases = {case["id"]: case for case in assessment_cases()}
    ambiguous = baseline(cases["indistinguishable_email_columns"])
    assert not any(rule.destination == "email" for rule in ambiguous.rules)
    outside = baseline(cases["slash_outside_sample"])
    assert (
        next(
            rule for rule in outside.rules if rule.destination == "signup_date"
        ).date_format
        is None
    )
    assert mapping_score(outside, cases["slash_outside_sample"])[
        "date_clarification_correct"
    ]


def test_predeclared_ground_truth_and_acceptable_alternatives():
    cases = assessment_cases()
    assert len(cases) == 16 and len({sha(case) for case in cases}) == 16
    for case in cases:
        rules = [
            Rule(
                destination=field,
                source=label["sources"][0],
                date_format=label["date_formats"][-1]
                if field == "signup_date"
                else None,
                categories=label["categories"],
            )
            for field, label in case["expected"].items()
            if label["sources"][0] is not None
        ]
        mapping = Mapping(rules=rules)
        assert mapping_score(mapping, case)["exact"]
        if not case["required_human_decisions"] and not case["expected_row_errors"]:
            assert validate_rows(source_rows(case), mapping, set())["invalid"] == 0


def test_model_failure_leaves_manual_mapping_usable(client, monkeypatch):
    from app import agents
    from app.cases import cases

    async def failed(*args, **kwargs):
        raise TimeoutError("Synthetic model failure")

    monkeypatch.setattr(agents, "suggest_mapping", failed)
    case = cases()[0]
    item = client.post(
        "/api/uploads",
        files={"file": ("manual-after-failure.csv", case.csv, "text/csv")},
    ).json()
    url = "/api/uploads/" + item["id"]
    assert client.post(url + "/suggest").status_code == 503
    assert (
        client.put(url + "/mapping", json=case.mapping.model_dump()).status_code == 200
    )
    validation = client.post(url + "/validate")
    assert validation.status_code == 200
    assert validation.json()["validation"]["valid"] == 1
