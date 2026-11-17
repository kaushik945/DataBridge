from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models import Chunk, DB
from app.retrieval import collection, ingest, retrieve


def test_reindex_replaces_changed_and_deleted_documents(
    client, tmp_path: Path, monkeypatch
):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text(
        "# Original\nOriginal customer schema.\n## Tier\npro is allowed.",
        encoding="utf-8",
    )
    second.write_text("# Dates\nUse explicit dates.", encoding="utf-8")
    with DB() as db:
        assert ingest(db, tmp_path) == 2
        old = set(db.scalars(select(Chunk.id).where(Chunk.collection == collection())))
        assert len(old) == 3
        assert ingest(db, tmp_path) == 0
        first.write_text("# Changed\nNew customer schema.", encoding="utf-8")
        second.unlink()
        assert ingest(db, tmp_path) == 1
        new = list(db.scalars(select(Chunk).where(Chunk.collection == collection())))
        assert len(new) == 1 and new[0].id not in old
        assert retrieve(db, "customer")[0]["title"] == "Changed"
        monkeypatch.setattr(settings, "ai_mode", "vertex")
        monkeypatch.setattr(settings, "embedding_model", "synthetic-model")
        monkeypatch.setattr(settings, "embedding_dimensions", 3)
        from app import retrieval

        monkeypatch.setattr(
            retrieval, "embed", lambda texts, task: [[1.0, 0.0, 0.0] for _ in texts]
        )
        assert ingest(db, tmp_path) == 1
        assert retrieve(db, "customer")[0]["title"] == "Changed"
        assert (
            len(list(db.scalars(select(Chunk)))) == 2
        )  # Isolated mock + real-shaped fixture collections.
