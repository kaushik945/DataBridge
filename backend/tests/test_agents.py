import asyncio

import pytest

from app import agents
from app.config import settings
from app.domain import Mapping


def test_sample_redaction():
    sample = agents.sanitized_sample(
        ["name", "email", "notes", "plan"],
        [
            {
                "values": {
                    "name": "Sensitive",
                    "email": "private@example.com",
                    "notes": "Private notes",
                    "plan": "pro",
                }
            }
        ],
    )
    assert sample == [
        {
            "name": "[REDACTED]",
            "email": "[REDACTED]",
            "notes": "[REDACTED]",
            "plan": "pro",
        }
    ]


def test_reviewer_revision_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    monkeypatch.setattr(agents, "retrieve", lambda *args: [])
    calls = []

    async def fake(name, schema, instruction, payload):
        calls.append(name)
        result = (
            agents.Proposal(mapping=Mapping(rules=[]), findings=[])
            if name == "Investigator"
            else agents.Review(findings=[])
        )
        return result, {"input_tokens": 10, "output_tokens": 5}

    monkeypatch.setattr(agents, "adk_call", fake)
    _, run = asyncio.run(agents.suggest_mapping(None, ["name"], []))
    assert calls == ["Investigator", "Reviewer", "Investigator", "Reviewer"]
    assert run["revision_count"] == 1
    assert (
        run["review"]["status"] == "needs_attention"
    )  # Unresolved findings are left to the human.
    assert run["usage"] == {"input_tokens": 40, "output_tokens": 20}


def test_vertex_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    monkeypatch.setattr(agents, "retrieve", lambda *args: [])

    async def failing(*args):
        raise TimeoutError("Synthetic failure")

    monkeypatch.setattr(agents, "adk_call", failing)
    with pytest.raises(TimeoutError):
        asyncio.run(agents.suggest_mapping(None, ["name"], []))


def test_installed_adk_structured_configuration():
    pytest.importorskip("google.adk")
    from google.adk.agents import LlmAgent
    from google.genai import types

    config = types.GenerateContentConfig(
        temperature=0,
        http_options=types.HttpOptions(
            timeout=45000, retry_options=types.HttpRetryOptions(attempts=2)
        ),
    )
    agent = LlmAgent(
        name="Investigator",
        model="configuration-check-only",
        instruction="No network call.",
        output_schema=agents.Proposal,
        generate_content_config=config,
    )
    assert agent.output_schema is agents.Proposal
    assert agent.generate_content_config.http_options.retry_options.attempts == 2
