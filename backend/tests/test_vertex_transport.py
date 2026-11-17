"""Transport contract checks with the pinned SDK; never make network calls."""

from types import SimpleNamespace

import asyncio
import pytest

from app import agents, retrieval
from app.config import settings


def test_embedding_single_input_no_truncation(monkeypatch):
    genai = pytest.importorskip("google.genai")
    calls = []

    def embed_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0, 0.0])])

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["vertexai"] is True
            assert kwargs["http_options"].retry_options.attempts == 1
            self.models = SimpleNamespace(embed_content=embed_content)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(genai, "Client", Client)
    monkeypatch.setattr(settings, "google_cloud_project", "offline-test")
    monkeypatch.setattr(settings, "embedding_model", "configured-model")
    monkeypatch.setattr(settings, "embedding_dimensions", 3)
    assert len(retrieval.embed(["first", "second"], "RETRIEVAL_DOCUMENT")) == 2
    assert [c["contents"] for c in calls] == [["first"], ["second"]]
    assert all(c["config"].auto_truncate is False for c in calls)


def test_adk_no_usage_is_unknown_and_calls_bounded(monkeypatch):
    pytest.importorskip("google.adk")
    import google.adk.runners

    class Runner:
        def __init__(self, **kwargs):
            assert kwargs["agent"].generate_content_config.max_output_tokens == 4096

        async def run_async(self, **kwargs):
            assert kwargs["run_config"].max_llm_calls == 1
            yield SimpleNamespace(
                usage_metadata=None,
                is_final_response=lambda: True,
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text='{"mapping":{"rules":[]},"findings":[]}')
                    ]
                ),
            )

    monkeypatch.setattr(google.adk.runners, "Runner", Runner)
    monkeypatch.setattr(settings, "google_cloud_project", "offline-test")
    monkeypatch.setattr(settings, "vertex_model", "configured-model")
    _, usage = asyncio.run(
        agents.adk_call("Investigator", agents.Proposal, "Test only.", {})
    )
    assert usage is None
    assert agents.sum_usage(None, {"input_tokens": 1, "output_tokens": 1}) is None


def test_citations_measured_before_invalid_ids_removed(monkeypatch):
    monkeypatch.setattr(settings, "ai_mode", "vertex")
    monkeypatch.setattr(
        agents, "retrieve", lambda *args: [{"id": "real", "text": "Rules"}]
    )

    async def call(*args):
        return agents.Proposal.model_validate(
            {
                "mapping": {
                    "rules": [
                        {
                            "destination": "name",
                            "source": "name",
                            "citations": ["real", "invented"],
                        }
                    ]
                },
                "findings": [],
            }
        ), None

    monkeypatch.setattr(agents, "adk_call", call)
    mapping, run = asyncio.run(
        agents.suggest_mapping(None, ["name"], [], reviewer=False)
    )
    assert mapping.rules[0].citations == ["real"]
    assert run["citation_audit"] == {"proposed": 2, "valid": 1}
    assert run["model"] == settings.vertex_model
    assert run["usage"] is None
