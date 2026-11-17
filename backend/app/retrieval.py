import hashlib
import re
import time
from pathlib import Path

from sqlalchemy import delete, select

from .config import settings
from .models import Chunk


def collection() -> str:
    if settings.ai_mode == "local":
        from .local_provider import identity

        return identity()
    return (
        "mock-v1"
        if settings.ai_mode == "mock"
        else f"vertex:{settings.embedding_model}:{settings.embedding_dimensions}"
    )


def embed(texts: list[str], task: str) -> list[list[float]]:
    if settings.ai_mode == "local":
        from .local_provider import embeddings

        return embeddings(texts, task)
    if not settings.embedding_model or not settings.google_cloud_project:
        raise ValueError("Set EMBEDDING_MODEL and GOOGLE_CLOUD_PROJECT")
    from google import genai
    from google.genai import types

    with genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        http_options=types.HttpOptions(
            timeout=settings.model_timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    ) as client:
        # Conservative across models: gemini-embedding-001 predict accepts one
        # input per request. Never silently embed only a truncated document.
        vectors = []
        for text in texts:
            response = client.models.embed_content(
                model=settings.embedding_model,
                contents=[text],
                config=types.EmbedContentConfig(
                    task_type=task,
                    output_dimensionality=settings.embedding_dimensions,
                    auto_truncate=False,
                ),
            )
            if not response.embeddings or len(response.embeddings) != 1:
                raise ValueError("Expected one embedding per input")
            vectors.append(response.embeddings[0].values)
    if len(vectors) != len(texts) or any(
        len(v) != settings.embedding_dimensions for v in vectors
    ):
        raise ValueError("Embedding model returned incompatible dimensions")
    return vectors


def ingest(db, root: Path) -> int:
    paths = sorted(root.glob("*.md"))
    if not paths:
        raise ValueError("No knowledge documents found")
    coll = collection()
    # All changes, deletions and replacements commit atomically; old versions cannot accumulate.
    db.execute(
        delete(Chunk).where(
            Chunk.collection == coll, Chunk.document.not_in([p.name for p in paths])
        )
    )
    changed = 0
    for path in paths:
        content = path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        previous = db.scalar(
            select(Chunk)
            .where(Chunk.collection == coll, Chunk.document == path.name)
            .limit(1)
        )
        if previous and previous.content_hash == content_hash:
            continue
        db.execute(
            delete(Chunk).where(Chunk.collection == coll, Chunk.document == path.name)
        )
        title = content.splitlines()[0].lstrip("# ")
        chunks = [s.strip() for s in re.split(r"(?m)(?=^## )", content) if s.strip()]
        vectors = (
            embed(chunks, "RETRIEVAL_DOCUMENT")
            if settings.ai_mode in ("vertex", "local")
            else [None] * len(chunks)
        )
        for i, (body, vector) in enumerate(zip(chunks, vectors, strict=True)):
            chunk_id = hashlib.sha256(
                f"{coll}:{path.name}:{content_hash}:{i}".encode()
            ).hexdigest()[:32]
            db.add(
                Chunk(
                    id=chunk_id,
                    collection=coll,
                    document=path.name,
                    title=title,
                    content_hash=content_hash,
                    ordinal=i,
                    text=body,
                    meta={
                        "heading": body.splitlines()[0],
                        "dimensions": len(vector) if vector else None,
                    },
                    embedding=vector,
                )
            )
        changed += 1
    db.commit()
    return changed


def retrieve(db, query: str, top_k: int = 8, timings: dict | None = None) -> list[dict]:
    started = time.monotonic()
    coll = collection()
    if timings is not None:
        timings["collection_identity_ms"] = round(
            (time.monotonic() - started) * 1000, 3
        )
    if settings.ai_mode in ("vertex", "local"):
        embedding_started = time.monotonic()
        vector = embed([query], "RETRIEVAL_QUERY")[0]
        if timings is not None:
            timings["query_embedding_ms"] = round(
                (time.monotonic() - embedding_started) * 1000, 3
            )
        search_started = time.monotonic()
        chunks = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.collection == coll)
                .order_by(Chunk.embedding.cosine_distance(vector))
                .limit(top_k)
            )
        )
        if timings is not None:
            timings["vector_search_ms"] = round(
                (time.monotonic() - search_started) * 1000, 3
            )
    else:
        terms = set(re.findall(r"[a-z]+", query.lower()))
        chunks = list(db.scalars(select(Chunk).where(Chunk.collection == coll)))
        chunks.sort(
            key=lambda c: (
                -len(terms & set(re.findall(r"[a-z]+", c.text.lower()))),
                c.document,
                c.ordinal,
            )
        )
        chunks = chunks[:top_k]
    if not chunks:
        raise ValueError("Knowledge collection is empty; run ingestion")
    return [
        {
            "id": c.id,
            "title": c.title,
            "text": c.text,
            "document": c.document,
            "hash": c.content_hash,
        }
        for c in chunks
    ]
