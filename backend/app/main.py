import datetime as dt
import asyncio
import hashlib
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as SQLSession

from .config import settings
from .domain import Mapping, digest, error_csv, mapping_issues, parse_csv, validate_rows
from .models import (
    Artifact,
    Audit,
    Customer,
    DB,
    ImportRequest,
    LoginAttempt,
    MappingVersion,
    Operator,
    Session,
    Upload,
    now,
    uid,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ai_mode not in ("mock", "vertex", "local"):
        raise RuntimeError("AI_MODE must be mock, local or vertex")
    yield


app = FastAPI(title="DataBridge", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method in ("POST", "PUT"):
        limit = (
            settings.max_upload_bytes + 65536
            if request.url.path == "/api/uploads"
            else 262144
        )
        parts = []
        size = 0
        async for part in request.stream():
            size += len(part)
            if size > limit:
                return JSONResponse(
                    {"detail": "Request exceeds the byte limit"}, status_code=413
                )
            parts.append(part)
        request._body = b"".join(parts)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def database():
    with DB() as db:
        yield db


def operator(request: Request, db: SQLSession = Depends(database)) -> Operator:
    session = db.get(Session, request.cookies.get("bridge_session", ""))
    if not session or session.expires < now():
        raise HTTPException(401, "Please sign in")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not secrets.compare_digest(
            request.headers.get("X-CSRF-Token", ""), session.csrf
        ):
            raise HTTPException(403, "Invalid CSRF token")
        if request.headers.get("origin") not in settings.allowed_origins.split(","):
            raise HTTPException(403, "Origin is not allowed")
    return db.get(Operator, session.operator_id)


def audit(db, op, action, upload=None, **details):
    db.add(
        Audit(
            operator_id=op.id,
            upload_id=upload.id if upload else None,
            action=action,
            details=details,
        )
    )


def owned(db, op, upload_id, lock=False) -> Upload:
    query = select(Upload).where(Upload.id == upload_id, Upload.operator_id == op.id)
    if lock:
        query = query.with_for_update()
    upload = db.scalar(query)
    if not upload:
        raise HTTPException(404, "Upload not found")
    return upload


def current_mapping(db, upload) -> MappingVersion | None:
    return db.scalar(
        select(MappingVersion).where(
            MappingVersion.upload_id == upload.id,
            MappingVersion.version == upload.version,
        )
    )


def serial_upload(db, upload):
    mapping = current_mapping(db, upload)
    return {
        "id": upload.id,
        "filename": upload.filename,
        "file_hash": upload.file_hash,
        "created": upload.created.isoformat(),
        "state": upload.state,
        "headers": upload.headers,
        "row_count": len(upload.rows),
        "samples": upload.rows[:5],
        "version": upload.version,
        "mapping": mapping.spec if mapping else {"rules": []},
        "validation": {k: v for k, v in upload.validation.items() if k != "rows"}
        if upload.validation
        else None,
        "approval": upload.approval,
        "result": upload.result,
        "agent_run": upload.agent_run,
        "mode": settings.ai_mode,
    }


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=256)


@app.get("/api/health")
def health(db: SQLSession = Depends(database)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "mode": settings.ai_mode}


@app.post("/api/login")
def login(
    body: Login,
    request: Request,
    response: Response,
    db: SQLSession = Depends(database),
):
    if request.headers.get("origin") not in settings.allowed_origins.split(","):
        raise HTTPException(403, "Origin is not allowed")
    # Serialize each client bucket across processes; do not trust forwarded headers.
    bucket = hashlib.sha256(
        (request.client.host if request.client else "unknown").encode()
    ).hexdigest()
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:bucket))"), {"bucket": bucket}
    )
    count = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.bucket == bucket,
            LoginAttempt.at > now() - dt.timedelta(minutes=5),
        )
    )
    if count >= 10:
        raise HTTPException(429, "Too many login attempts. Retry in five minutes.")
    db.add(LoginAttempt(bucket=bucket))
    account = db.scalar(select(Operator).where(Operator.username == body.username))
    valid = False
    if account:
        try:
            valid = PasswordHasher().verify(account.password_hash, body.password)
        except VerificationError:
            pass
    else:
        # Comparable hashing work for unknown accounts.
        PasswordHasher().hash(body.password)
    if not valid:
        db.commit()
        raise HTTPException(401, "Invalid username or password")
    session = Session(
        id=secrets.token_urlsafe(32),
        operator_id=account.id,
        csrf=secrets.token_urlsafe(32),
        expires=now() + dt.timedelta(hours=8),
    )
    db.add(session)
    audit(db, account, "login")
    db.commit()
    response.set_cookie(
        "bridge_session",
        session.id,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=28800,
    )
    return {
        "username": account.username,
        "csrf": session.csrf,
        "mode": settings.ai_mode,
    }


@app.get("/api/session")
def session_info(
    request: Request, op=Depends(operator), db: SQLSession = Depends(database)
):
    session = db.get(Session, request.cookies["bridge_session"])
    return {"username": op.username, "csrf": session.csrf, "mode": settings.ai_mode}


@app.post("/api/logout")
def logout(
    request: Request,
    response: Response,
    op=Depends(operator),
    db: SQLSession = Depends(database),
):
    db.delete(db.get(Session, request.cookies["bridge_session"]))
    db.commit()
    response.delete_cookie("bridge_session")
    return {"ok": True}


@app.post("/api/uploads")
def upload(
    file: UploadFile = File(...),
    op=Depends(operator),
    db: SQLSession = Depends(database),
):
    # Read one bounded chunk, never materialize an unbounded upload in application memory.
    data = file.file.read(settings.max_upload_bytes + 1)
    try:
        headers, rows = parse_csv(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    recent = db.scalar(
        select(func.count())
        .select_from(Upload)
        .where(
            Upload.operator_id == op.id,
            Upload.created > now() - dt.timedelta(minutes=1),
        )
    )
    if recent >= settings.uploads_per_minute:
        raise HTTPException(429, "Upload limit reached. Retry in a minute.")
    item = Upload(
        operator_id=op.id,
        filename=(file.filename or "customers.csv")[:255],
        file_hash=hashlib.sha256(data).hexdigest(),
        headers=headers,
        rows=rows,
    )
    db.add(item)
    db.flush()
    object_key = None
    if settings.gcs_bucket:
        from google.cloud import storage

        object_key = f"uploads/{item.id}/{item.file_hash}.csv"
        try:
            storage.Client().bucket(settings.gcs_bucket).blob(
                object_key
            ).upload_from_string(
                data,
                content_type="text/csv",
                timeout=30,
                retry=None,
                if_generation_match=0,
            )
        except Exception as exc:
            raise HTTPException(
                503, "Original file storage failed; retry upload"
            ) from exc
    audit(db, op, "uploaded", item, rows=len(rows), object_key=object_key)
    db.commit()
    return serial_upload(db, item)


@app.get("/api/uploads")
def history(op=Depends(operator), db: SQLSession = Depends(database)):
    return [
        serial_upload(db, u)
        for u in db.scalars(
            select(Upload)
            .where(Upload.operator_id == op.id)
            .order_by(Upload.created.desc())
            .limit(100)
        )
    ]


@app.get("/api/uploads/{upload_id}")
def detail(upload_id: str, op=Depends(operator), db: SQLSession = Depends(database)):
    return serial_upload(db, owned(db, op, upload_id))


def save_mapping(db, op, item, mapping):
    if item.state == "IMPORTED":
        raise HTTPException(409, "Imported files are immutable; upload a new file")
    unknown = [r.source for r in mapping.rules if r.source not in item.headers]
    if unknown:
        raise HTTPException(422, "Mapping refers to unknown columns")
    item.version += 1
    spec = mapping.model_dump()
    db.add(
        MappingVersion(
            upload_id=item.id, version=item.version, spec=spec, hash=digest(spec)
        )
    )
    item.validation = None
    item.approval = None
    item.state = "NEEDS_REVIEW"
    audit(db, op, "mapping_saved", item, version=item.version)


@app.put("/api/uploads/{upload_id}/mapping")
def mapping_save(
    upload_id: str,
    mapping: Mapping,
    op=Depends(operator),
    db: SQLSession = Depends(database),
):
    item = owned(db, op, upload_id, True)
    save_mapping(db, op, item, mapping)
    db.commit()
    return serial_upload(db, item)


@app.post("/api/uploads/{upload_id}/suggest")
def suggest(upload_id: str, op=Depends(operator), db: SQLSession = Depends(database)):
    from .agents import suggest_mapping

    item = owned(db, op, upload_id, True)
    if item.state == "IMPORTED":
        raise HTTPException(409, "Imported files are immutable")
    try:
        mapping, run = asyncio.run(
            suggest_mapping(
                db,
                item.headers,
                item.rows,
                category_strategy=settings.tier_mapping_strategy,
            )
        )
    except Exception as exc:
        # No credential errors or sensitive prompts in user-facing errors or logs.
        db.add(
            Artifact(
                upload_id=item.id,
                kind="agent_failure",
                version=item.version,
                content={
                    "mode": settings.ai_mode,
                    "status": "failed",
                    "at": now().isoformat(),
                },
            )
        )
        audit(db, op, "agents_failed", item, mode=settings.ai_mode)
        db.commit()
        raise HTTPException(
            503,
            "Local AI failed: check Ollama is running, the model is downloaded, host.docker.internal is reachable and RAM/VRAM is available. No fallback was used."
            if settings.ai_mode == "local"
            else "AI request failed or timed out. Check configuration and retry, or use manual mapping.",
        ) from exc
    save_mapping(db, op, item, mapping)
    run["mapping_version"] = item.version
    item.agent_run = run
    db.add(
        Artifact(upload_id=item.id, kind="agent_run", version=item.version, content=run)
    )
    audit(db, op, "agents_completed", item, mode=settings.ai_mode)
    db.commit()
    return serial_upload(db, item)


@app.post("/api/uploads/{upload_id}/category-preview")
def preview_categories(
    upload_id: str,
    mapping: Mapping,
    op=Depends(operator),
    db: SQLSession = Depends(database),
):
    from .categories import category_preview

    item = owned(db, op, upload_id)
    return category_preview(
        mapping,
        item.headers,
        item.rows,
        set(db.scalars(select(Customer.email))),
        (item.agent_run or {}).get("evidence", []),
    )


@app.post("/api/uploads/{upload_id}/validate")
def validate(upload_id: str, op=Depends(operator), db: SQLSession = Depends(database)):
    item = owned(db, op, upload_id, True)
    if item.state == "IMPORTED":
        raise HTTPException(409, "Imported files are immutable")
    mapping = current_mapping(db, item)
    if not mapping:
        raise HTTPException(409, "Save a mapping first")
    spec = Mapping.model_validate(mapping.spec)
    issues = mapping_issues(spec, item.headers)
    if issues:
        raise HTTPException(422, "; ".join(issues))
    result = validate_rows(item.rows, spec, set(db.scalars(select(Customer.email))))
    item.validation = {
        **result,
        "file_hash": item.file_hash,
        "mapping_hash": mapping.hash,
        "version": item.version,
        "hash": digest(result),
        "mode": settings.ai_mode,
        "at": now().isoformat(),
    }
    item.approval = None
    item.state = "VALIDATED"
    db.add(
        Artifact(
            upload_id=item.id,
            kind="validation",
            version=item.version,
            content=item.validation,
        )
    )
    audit(db, op, "validated", item, valid=result["valid"], invalid=result["invalid"])
    db.commit()
    return serial_upload(db, item)


@app.get("/api/uploads/{upload_id}/rows")
def rows(
    upload_id: str,
    page: int = 1,
    status: Literal["all", "valid", "invalid"] = "all",
    op=Depends(operator),
    db: SQLSession = Depends(database),
):
    item = owned(db, op, upload_id)
    if page < 1:
        raise HTTPException(422, "Page must be positive")
    results = item.validation["rows"] if item.validation else item.rows
    if status != "all":
        results = [r for r in results if r.get("valid") == (status == "valid")]
    return {
        "rows": results[(page - 1) * 25 : page * 25],
        "total": len(results),
        "page": page,
        "page_size": 25,
    }


class ApprovalBody(BaseModel):
    version: int
    validation_hash: str
    policy: Literal["valid_only", "cancel"]


@app.post("/api/uploads/{upload_id}/approve")
def approve(
    upload_id: str,
    body: ApprovalBody,
    op=Depends(operator),
    db: SQLSession = Depends(database),
):
    item = owned(db, op, upload_id, True)
    if item.state not in ("VALIDATED", "APPROVED") or not item.validation:
        raise HTTPException(409, "Validate this mapping before approval")
    if body.version != item.version or body.validation_hash != item.validation["hash"]:
        raise HTTPException(409, "Validation changed; reload and review")
    if body.policy == "cancel":
        item.approval = None
        item.validation = None
        item.state = "NEEDS_REVIEW"
        audit(db, op, "approval_cancelled", item)
    else:
        if not item.validation["valid"]:
            raise HTTPException(409, "No valid rows to import")
        item.approval = {
            "id": uid(),
            "operator_id": op.id,
            "at": now().isoformat(),
            "file_hash": item.file_hash,
            "mapping_hash": item.validation["mapping_hash"],
            "version": item.version,
            "validation_hash": body.validation_hash,
            "policy": body.policy,
        }
        item.state = "APPROVED"
        db.add(
            Artifact(
                upload_id=item.id,
                kind="approval",
                version=item.version,
                content=item.approval,
            )
        )
        audit(db, op, "approved", item, **item.approval)
    db.commit()
    return serial_upload(db, item)


class ImportBody(BaseModel):
    approval_id: str
    idempotency_key: str = Field(min_length=8, max_length=100)


@app.post("/api/uploads/{upload_id}/import")
def execute_import(
    upload_id: str,
    body: ImportBody,
    op=Depends(operator),
    db: SQLSession = Depends(database),
):
    # Serializes a reused key across uploads as well as repeated requests to one upload.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": body.idempotency_key},
    )
    item = owned(db, op, upload_id, True)
    fingerprint = digest(
        {"upload": item.id, "approval": body.approval_id, "operator": op.id}
    )
    previous = db.get(ImportRequest, body.idempotency_key)
    if previous:
        if previous.fingerprint != fingerprint:
            raise HTTPException(
                409, "Idempotency key already used for different content"
            )
        return previous.result
    if (
        item.state != "APPROVED"
        or not item.approval
        or body.approval_id != item.approval["id"]
    ):
        raise HTTPException(409, "Exact current approval is required")
    mapping = current_mapping(db, item)
    approval = item.approval
    if (
        approval["file_hash"] != item.file_hash
        or approval["mapping_hash"] != mapping.hash
        or approval["version"] != item.version
        or approval["validation_hash"] != item.validation["hash"]
    ):
        raise HTTPException(409, "Approval is stale; revalidate")
    accepted = [r for r in item.validation["rows"] if r["valid"]]
    # A small app: serialize destination writes, then recheck under the same transaction.
    # Unique email constraints also protect against writers outside this application.
    db.execute(text("SELECT pg_advisory_xact_lock(48121901)"))
    emails = [r["after"]["email"] for r in accepted]
    conflict = db.scalar(select(Customer.id).where(Customer.email.in_(emails)).limit(1))
    if conflict:
        item.approval = None
        item.validation = None
        item.state = "NEEDS_REVIEW"
        audit(db, op, "import_conflict", item)
        db.commit()
        raise HTTPException(
            409, "Destination changed after validation. No rows imported; revalidate."
        )
    result = {
        "upload_id": item.id,
        "imported": len(accepted),
        "rejected": item.validation["invalid"],
        "mode": settings.ai_mode,
        "at": now().isoformat(),
        "approval_id": approval["id"],
    }
    try:
        for row in accepted:
            values = dict(row["after"])
            values["signup_date"] = dt.date.fromisoformat(values["signup_date"])
            db.add(Customer(**values, upload_id=item.id))
        item.state = "IMPORTED"
        item.result = result
        db.add(
            ImportRequest(
                key=body.idempotency_key,
                fingerprint=fingerprint,
                upload_id=item.id,
                result=result,
            )
        )
        audit(
            db,
            op,
            "imported",
            item,
            imported=len(accepted),
            rejected=result["rejected"],
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        item = owned(db, op, upload_id, True)
        item.state = "NEEDS_REVIEW"
        item.approval = None
        item.validation = None
        audit(db, op, "import_conflict", item)
        db.commit()
        raise HTTPException(
            409, "Destination conflict. Transaction rolled back; revalidate."
        ) from exc
    return result


@app.get("/api/uploads/{upload_id}/errors", response_class=PlainTextResponse)
def report(upload_id: str, op=Depends(operator), db: SQLSession = Depends(database)):
    item = owned(db, op, upload_id)
    if not item.validation:
        raise HTTPException(409, "Validate before downloading errors")
    return PlainTextResponse(
        error_csv(item.validation, item.validation["mode"]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="rejected-rows.csv"'},
    )


@app.get("/api/customers")
def customers(page: int = 1, op=Depends(operator), db: SQLSession = Depends(database)):
    if page < 1:
        raise HTTPException(422, "Page must be positive")
    total = db.scalar(select(func.count()).select_from(Customer))
    records = db.scalars(
        select(Customer).order_by(Customer.email).offset((page - 1) * 25).limit(25)
    )
    return {
        "total": total,
        "rows": [
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "signup_date": c.signup_date.isoformat(),
                "subscription_tier": c.subscription_tier,
                "country_code": c.country_code,
            }
            for c in records
        ],
    }


@app.get("/api/evidence/{chunk_id}")
def evidence(chunk_id: str, op=Depends(operator), db: SQLSession = Depends(database)):
    from .models import Chunk

    chunk = db.get(Chunk, chunk_id)
    if not chunk:
        snapshot = db.scalar(
            select(Artifact)
            .join(Upload, Upload.id == Artifact.upload_id)
            .where(
                Upload.operator_id == op.id,
                Artifact.kind == "agent_run",
                Artifact.content["evidence"].contains([{"id": chunk_id}]),
            )
            .limit(1)
        )
        if snapshot:
            return next(e for e in snapshot.content["evidence"] if e["id"] == chunk_id)
        raise HTTPException(
            404, "Evidence not found; reindex and regenerate suggestions"
        )
    return {
        "id": chunk.id,
        "title": chunk.title,
        "text": chunk.text,
        "document": chunk.document,
        "hash": chunk.content_hash,
    }


# The optional Cloud Run image serves the Vite output on the same origin as /api.
from pathlib import Path  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

if Path("/app/static").is_dir():
    app.mount("/", StaticFiles(directory="/app/static", html=True), name="web")
