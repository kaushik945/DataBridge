from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cases import cases
from app.domain import mapping_issues, parse_csv
from app.main import app
from app.models import Customer, DB


def prepared(client, case=None):
    case = case or cases()[0]
    response = client.post(
        "/api/uploads", files={"file": ("case.csv", case.csv, "text/csv")}
    )
    assert response.status_code == 200, response.text
    item = response.json()
    url = "/api/uploads/" + item["id"]
    response = client.put(url + "/mapping", json=case.mapping.model_dump())
    assert response.status_code == 200, response.text
    response = client.post(url + "/validate")
    assert response.status_code == 200, response.text
    return url, response.json()


def approved(client, case=None):
    url, item = prepared(client, case)
    response = client.post(
        url + "/approve",
        json={
            "version": item["version"],
            "validation_hash": item["validation"]["hash"],
            "policy": "valid_only",
        },
    )
    assert response.status_code == 200, response.text
    return url, response.json()


def test_manual_approval_retry_and_invalidation(client):
    url, item = prepared(client)
    assert (
        client.post(
            url + "/import",
            json={"approval_id": "none", "idempotency_key": "not-approved"},
        ).status_code
        == 409
    )
    body = {
        "version": item["version"],
        "validation_hash": item["validation"]["hash"],
        "policy": "valid_only",
    }
    item = client.post(url + "/approve", json=body).json()
    old_id = item["approval"]["id"]
    changed = client.put(url + "/mapping", json=item["mapping"]).json()
    assert (
        changed["state"] == "NEEDS_REVIEW"
        and changed["approval"] is None
        and changed["validation"] is None
    )
    assert (
        client.post(
            url + "/import",
            json={"approval_id": old_id, "idempotency_key": "stale-approval"},
        ).status_code
        == 409
    )
    item = client.post(url + "/validate").json()
    body.update(version=item["version"], validation_hash=item["validation"]["hash"])
    item = client.post(url + "/approve", json=body).json()
    req = {"approval_id": item["approval"]["id"], "idempotency_key": "same-request-key"}
    first = client.post(url + "/import", json=req)
    assert first.status_code == 200, first.text
    assert client.post(url + "/import", json=req).json() == first.json()
    assert (
        client.post(
            url + "/import", json={**req, "approval_id": "different"}
        ).status_code
        == 409
    )
    assert client.get("/api/customers").json()["total"] == 1


def test_concurrent_identical_import(client):
    url, item = approved(client)
    body = {"approval_id": item["approval"]["id"], "idempotency_key": "concurrent-key"}

    def run(_):
        with TestClient(app) as c:
            c.cookies.update(client.cookies)
            c.headers.update(
                {
                    "Origin": "http://localhost:5173",
                    "X-CSRF-Token": client.headers["X-CSRF-Token"],
                }
            )
            return c.post(url + "/import", json=body)

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(run, range(4)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert all(r.json() == responses[0].json() for r in responses)
    assert client.get("/api/customers").json()["total"] == 1


def test_conflict_rolls_back_entire_batch(client):
    first = cases()[0]
    second = cases()[0]
    second.csv += b"Other,other@example.com,2025-01-01,basic,IN\n"
    url, item = approved(client, second)
    other_url, other = approved(client, first)
    response = client.post(
        other_url + "/import",
        json={
            "approval_id": other["approval"]["id"],
            "idempotency_key": "other-import",
        },
    )
    assert response.status_code == 200
    response = client.post(
        url + "/import",
        json={
            "approval_id": item["approval"]["id"],
            "idempotency_key": "conflicting-import",
        },
    )
    assert response.status_code == 409
    with DB() as db:
        assert list(db.scalars(select(Customer.email))) == ["alex@example.com"]
    detail = client.get(url).json()
    assert detail["state"] == "NEEDS_REVIEW" and detail["approval"] is None


def test_partial_policy_and_error_report(client):
    case = next(c for c in cases() if c.name == "duplicate_file")
    url, item = approved(client, case)
    assert item["validation"]["invalid"] == 1
    result = client.post(
        url + "/import",
        json={"approval_id": item["approval"]["id"], "idempotency_key": "partial-rows"},
    ).json()
    assert result["imported"] == 1 and result["rejected"] == 1
    assert "mock,3," in client.get(url + "/errors").text


def test_auth_csrf_and_ownership(client):
    url, _ = prepared(client)
    with TestClient(app) as anon:
        for path in [
            "/api/uploads",
            url,
            url + "/errors",
            "/api/customers",
            "/api/evidence/invalid",
        ]:
            assert anon.get(path).status_code == 401
    saved = client.headers.pop("X-CSRF-Token")
    assert client.post(url + "/validate").status_code == 403
    client.headers["X-CSRF-Token"] = saved
    client.headers["Origin"] = "https://evil.example"
    assert client.post(url + "/validate").status_code == 403


def test_mock_suggestions_and_citations(client):
    case = next(c for c in cases() if c.name == "tier_alias")
    response = client.post("/api/uploads", files={"file": ("case.csv", case.csv)})
    url = "/api/uploads/" + response.json()["id"]
    response = client.post(url + "/suggest")
    assert response.status_code == 200, response.text
    item = response.json()
    assert item["agent_run"]["mode"] == "mock" and item["agent_run"]["usage"] is None
    tier = next(
        r for r in item["mapping"]["rules"] if r["destination"] == "subscription_tier"
    )
    assert tier["categories"] == {"starter": "basic"} and tier["citations"]
    assert client.get("/api/evidence/" + tier["citations"][0]).status_code == 200
    from app.models import Chunk

    with DB() as db:
        db.delete(db.get(Chunk, tier["citations"][0]))
        db.commit()
    archived = client.get("/api/evidence/" + tier["citations"][0])
    assert archived.status_code == 200
    assert "starter" in archived.json()["text"]


def test_reused_key_across_uploads_and_owner_isolation(client):
    from app.models import Operator, Upload
    from argon2 import PasswordHasher

    url, item = approved(client)
    body = {
        "approval_id": item["approval"]["id"],
        "idempotency_key": "global-key-reuse",
    }
    assert client.post(url + "/import", json=body).status_code == 200
    other_case = cases()[0]
    other_case.csv = other_case.csv.replace(b"alex@example.com", b"other@example.com")
    other_url, other = approved(client, other_case)
    response = client.post(
        other_url + "/import", json={**body, "approval_id": other["approval"]["id"]}
    )
    assert response.status_code == 409
    with DB() as db:
        another = Operator(
            username="isolation-test",
            password_hash=PasswordHasher().hash("unused-test-password"),
        )
        db.add(another)
        db.flush()
        upload = db.get(Upload, other["id"])
        upload.operator_id = another.id
        db.commit()
    for path in [other_url, other_url + "/rows", other_url + "/errors"]:
        assert client.get(path).status_code == 404


def test_request_upload_and_login_limits(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_bytes", 16)
    response = client.post("/api/uploads", files={"file": ("big.csv", b"x" * 70000)})
    assert response.status_code == 413 and "byte limit" in response.json()["detail"]
    response = client.post("/api/uploads", files={"file": ("big.csv", b"x" * 17)})
    assert response.status_code == 422
    for _ in range(9):
        assert (
            client.post(
                "/api/login", json={"username": "tester", "password": "wrong-password"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/login", json={"username": "tester", "password": "wrong-password"}
        ).status_code
        == 429
    )


@pytest.mark.parametrize(
    "case",
    [
        c
        for c in cases()
        if not c.parse_error and not mapping_issues(c.mapping, parse_csv(c.csv)[0])
    ],
    ids=lambda c: c.name,
)
def test_import_ground_truth(client, case):
    url, item = prepared(client, case)
    expected = len(item["samples"]) - len(case.errors)
    assert item["validation"]["valid"] == expected
    if expected:
        item = client.post(
            url + "/approve",
            json={
                "version": item["version"],
                "validation_hash": item["validation"]["hash"],
                "policy": "valid_only",
            },
        ).json()
        response = client.post(
            url + "/import",
            json={
                "approval_id": item["approval"]["id"],
                "idempotency_key": "ground-truth-" + case.name,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["imported"] == expected
        assert client.get("/api/customers").json()["total"] == expected
    else:
        assert (
            client.post(
                url + "/approve",
                json={
                    "version": item["version"],
                    "validation_hash": item["validation"]["hash"],
                    "policy": "valid_only",
                },
            ).status_code
            == 409
        )
