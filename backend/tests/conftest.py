import os
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.models import Base, DB, Operator, engine
from app.retrieval import ingest


@pytest.fixture
def client():
    if (
        not os.environ.get("DATABASE_URL", "")
        .split("?")[0]
        .endswith("/databridge_test")
    ):
        pytest.skip("Integration tests require dedicated databridge_test database")
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)
        conn.execute(text("TRUNCATE " + ", ".join(Base.metadata.tables) + " CASCADE"))
    with DB() as db:
        db.add(
            Operator(
                username="tester",
                password_hash=PasswordHasher().hash("test-password-only"),
            )
        )
        db.commit()
        ingest(
            db,
            Path("knowledge")
            if Path("knowledge").exists()
            else Path("../docs/knowledge"),
        )
    with TestClient(app) as c:
        c.headers["Origin"] = "http://localhost:5173"
        response = c.post(
            "/api/login", json={"username": "tester", "password": "test-password-only"}
        )
        assert response.status_code == 200
        c.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield c
