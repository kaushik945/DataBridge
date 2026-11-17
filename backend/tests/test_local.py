import httpx
import pytest

from app import local_provider
from app.agents import (
    Proposal,
    check_proposal,
    grounded_proposal_schema,
    require_human_slash_format,
)
from app.config import settings


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://192.168.1.10:11434",
        "http://localhost:11434/v1",
        "http://user:pass@localhost:11434",
    ],
)
def test_reject_remote_endpoint(monkeypatch, url):
    monkeypatch.setattr(settings, "local_endpoint", url)
    with pytest.raises(local_provider.LocalAIError):
        local_provider.endpoint()


@pytest.mark.parametrize("name", ["qwen3:4b-cloud", "openai/gpt-4", "qwen3"])
def test_reject_remote_model(name):
    with pytest.raises(local_provider.LocalAIError):
        local_provider.model_name(name)


def test_cpu_prefix_and_dimensions(monkeypatch):
    calls = []

    def fake(path, body=None):
        calls.append(body)
        return {"embeddings": [[0.1] * 768]}

    monkeypatch.setattr(local_provider, "request", fake)
    assert len(local_provider.embeddings(["hello"], "RETRIEVAL_QUERY")[0]) == 768
    assert calls[0]["input"] == ["search_query: hello"]
    assert calls[0]["options"]["num_gpu"] == 0
    assert calls[0]["truncate"] is False
    local_provider.embeddings(["rules"], "RETRIEVAL_DOCUMENT")
    assert calls[1]["input"] == ["search_document: rules"]


def test_ai_slash_date_choice_is_cleared_before_human_approval():
    proposal = Proposal.model_validate(
        {
            "mapping": {
                "rules": [
                    {
                        "destination": "signup_date",
                        "source": "joined",
                        "date_format": "%d/%m/%Y",
                    }
                ]
            },
            "findings": [],
        }
    )
    require_human_slash_format(proposal, [{"values": {"joined": "03/04/2025"}}])
    assert proposal.mapping.rules[0].date_format is None
    assert (
        proposal.findings == []
    )  # The application supplies the verified date finding.


def test_failed_local_transport_never_falls_back(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("Synthetic failure")

    monkeypatch.setattr(httpx.Client, "get", fail)
    with pytest.raises(local_provider.LocalAIError, match="Cannot reach Ollama"):
        local_provider.request("/api/tags")


def test_grounded_schema_forbids_invented_sources_and_citations():
    from pydantic import ValidationError

    schema = grounded_proposal_schema(["actual_column"], [{"id": "actual_chunk"}])
    value = {
        "mapping": {
            "rules": [
                {
                    "destination": "name",
                    "source": "actual_column",
                    "citations": ["actual_chunk"],
                }
            ]
        },
        "findings": [],
    }
    assert schema.model_validate(value).mapping.rules[0].source == "actual_column"
    value["mapping"]["rules"][0]["source"] = "invented"
    with pytest.raises(ValidationError):
        schema.model_validate(value)
    value["mapping"]["rules"][0]["source"] = "actual_column"
    value["mapping"]["rules"][0]["citations"] = ["invented"]
    with pytest.raises(ValidationError):
        schema.model_validate(value)
    value["mapping"]["rules"][0]["citations"] = ["actual_chunk"]
    del value["mapping"]["rules"][0]["destination"]
    with pytest.raises(ValidationError):
        schema.model_validate(value)


def test_local_generations_use_shared_configured_model(monkeypatch):
    pytest.importorskip("litellm")
    from google.adk.models.lite_llm import LiteLlm

    model = local_provider.generation_model()
    assert isinstance(model, LiteLlm)
    assert model.model == "ollama_chat/qwen3:4b"


def test_undocumented_alias_is_flagged_even_when_words_cooccur():
    proposal = Proposal.model_validate(
        {
            "mapping": {
                "rules": [
                    {
                        "destination": "subscription_tier",
                        "source": "plan",
                        "categories": {"gold": "basic"},
                        "citations": ["real"],
                    }
                ]
            },
            "findings": [],
        }
    )
    findings = check_proposal(
        proposal,
        ["plan"],
        [{"id": "real", "text": "basic is allowed; gold is undocumented"}],
    )
    assert any("not an approved AI alias" in finding for finding in findings)
    # The human may still deliberately create an explicit pair through manual mapping.
    assert proposal.mapping.rules[0].categories == {"gold": "basic"}
