"""Ollama-only transport. No remote provider names, credentials or fallbacks."""

import json
import re
import time
from urllib.parse import urlparse

import httpx

from .config import settings
from .profiling import span


class LocalAIError(ValueError):
    pass


def endpoint() -> str:
    value = settings.local_endpoint.rstrip("/")
    url = urlparse(value)
    if (
        url.scheme != "http"
        or url.hostname not in {"localhost", "127.0.0.1", "host.docker.internal"}
        or url.path
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise LocalAIError(
            "Local endpoint must be an HTTP loopback or Docker host address, without credentials or a path"
        )
    return value


def model_name(value: str) -> str:
    if not re.fullmatch(r"[\w.-]+:[\w.-]+", value) or "cloud" in value.lower():
        raise LocalAIError(
            "Use a downloaded local model:tag, never a cloud model or provider path"
        )
    return value


def request(path: str, body: dict | None = None) -> dict:
    try:
        with httpx.Client(
            base_url=endpoint(),
            timeout=settings.local_timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = (
                client.post(path, json=body) if body is not None else client.get(path)
            )
            if response.status_code == 404:
                raise LocalAIError(
                    "Ollama model missing or wrong endpoint; run the documented ollama pull command"
                )
            if response.status_code >= 400:
                raise LocalAIError(
                    "Ollama rejected the request; check model availability, context size and RAM/VRAM in server logs"
                )
            return response.json()
    except httpx.TimeoutException as exc:
        raise LocalAIError(
            "Ollama timed out; check GPU acceleration or reduce context/model size"
        ) from exc
    except httpx.TransportError as exc:
        raise LocalAIError(
            "Cannot reach Ollama; start it and check LOCAL_ENDPOINT from inside the API container"
        ) from exc


def identity() -> str:
    name = model_name(settings.local_embedding_model)
    models = request("/api/tags").get("models", [])
    match = next((m for m in models if m["name"] == name), None)
    if not match:
        raise LocalAIError(f"Download the configured local embedding model: {name}")
    return f"local:{name}:{match['digest']}:768:nomic-prefix-v1"


def embeddings(texts: list[str], task: str) -> list[list[float]]:
    name = model_name(settings.local_embedding_model)
    if name != "nomic-embed-text:v1.5":
        raise LocalAIError(
            "This embedding adapter supports nomic-embed-text:v1.5 prefixes and 768 dimensions; add an explicit adapter before switching families"
        )
    prefix = "search_query: " if task == "RETRIEVAL_QUERY" else "search_document: "
    vectors = []
    for text in texts:
        result = request(
            "/api/embed",
            {
                "model": name,
                "input": [prefix + text],
                "truncate": False,
                "options": {"num_gpu": 0, "num_ctx": 2048},
                "keep_alive": 0,
            },
        )
        values = result.get("embeddings", [])
        if len(values) != 1 or len(values[0]) != 768:
            raise LocalAIError(
                "Embedding/index mismatch: expected one 768-dimensional vector; reindex the configured model"
            )
        vectors.append(values[0])
    return vectors


def generation_model(trace: dict | None = None):
    import os

    os.environ["OLLAMA_API_BASE"] = endpoint()
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    os.environ["DO_NOT_TRACK"] = "true"
    from google.adk.models.lite_llm import LiteLlm, LiteLLMClient

    class ProfiledClient(LiteLLMClient):
        async def acompletion(self, **kwargs):
            from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

            request_started = None

            async def record_request(request):
                nonlocal request_started
                request_started = time.monotonic()
                if trace is not None:
                    body = json.loads(request.content)
                    trace["http_attempts"] = trace.get("http_attempts", 0) + 1
                    trace["transport_request"] = {
                        "body_bytes": len(request.content),
                        "message_characters": [
                            len(m.get("content") or "")
                            for m in body.get("messages", [])
                        ],
                        "options": body.get("options"),
                        "stream": body.get("stream"),
                    }

            async def record_response(response):
                with span(trace, "http_response_read", "http_request"):
                    await response.aread()
                if trace is not None and request_started is not None:
                    ended = time.monotonic()
                    origin = trace.get("_started", request_started)
                    trace.setdefault("spans", []).append(
                        {
                            "name": "http_request",
                            "parent": "litellm_completion",
                            "start_ms": round((request_started - origin) * 1000, 3),
                            "end_ms": round((ended - origin) * 1000, 3),
                            "duration_ms": round((ended - request_started) * 1000, 3),
                        }
                    )
                if trace is not None and response.status_code == 200:
                    body = response.json()
                    trace["provider"] = {
                        key: body.get(key)
                        for key in (
                            "total_duration",
                            "load_duration",
                            "prompt_eval_duration",
                            "eval_duration",
                            "prompt_eval_count",
                            "eval_count",
                            "done_reason",
                        )
                    }

            with span(trace, "http_client_setup", "adk_invocation"):
                handler = AsyncHTTPHandler(
                    timeout=settings.local_timeout_seconds,
                    event_hooks={
                        "request": [record_request],
                        "response": [record_response],
                    },
                )
            try:
                with span(trace, "litellm_completion", "adk_invocation"):
                    return await super().acompletion(**kwargs, client=handler)
            finally:
                with span(trace, "http_client_close", "adk_invocation"):
                    await handler.client.aclose()

    return LiteLlm(
        model="ollama_chat/" + model_name(settings.local_model),
        api_base=endpoint(),
        num_ctx=settings.local_context,
        num_predict=settings.local_output_tokens,
        think=False,
        temperature=0,
        timeout=settings.local_timeout_seconds,
        num_retries=0,
        keep_alive="10m",
        llm_client=ProfiledClient(),
    )


def diagnostics() -> dict:
    available = [m["name"] for m in request("/api/tags").get("models", [])]
    return {
        "endpoint": endpoint(),
        "version": request("/api/version"),
        "generation_model": model_name(settings.local_model),
        "generation_downloaded": settings.local_model in available,
        "available_models": available,
        "embedding_collection": identity(),
        "loaded": request("/api/ps"),
    }
