import datetime as dt
import uuid

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from pgvector.sqlalchemy import Vector

from .config import settings


def uid() -> str:
    return str(uuid.uuid4())


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Operator(Base):
    __tablename__ = "operators"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    operator_id: Mapped[str] = mapped_column(ForeignKey("operators.id"))
    csrf: Mapped[str] = mapped_column(String)
    expires: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    bucket: Mapped[str] = mapped_column(String, index=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    operator_id: Mapped[str] = mapped_column(ForeignKey("operators.id"))
    filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64))
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    state: Mapped[str] = mapped_column(String, default="UPLOADED")
    headers: Mapped[list] = mapped_column(JSONB)
    rows: Mapped[list] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=0)
    validation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approval: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    agent_run: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class MappingVersion(Base):
    __tablename__ = "mapping_versions"
    __table_args__ = (UniqueConstraint("upload_id", "version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    upload_id: Mapped[str] = mapped_column(ForeignKey("uploads.id"))
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSONB)
    hash: Mapped[str] = mapped_column(String(64))


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    signup_date: Mapped[dt.date] = mapped_column(Date)
    subscription_tier: Mapped[str] = mapped_column(String(20))
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    upload_id: Mapped[str] = mapped_column(ForeignKey("uploads.id"))


class ImportRequest(Base):
    __tablename__ = "import_requests"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    upload_id: Mapped[str] = mapped_column(ForeignKey("uploads.id"))
    result: Mapped[dict] = mapped_column(JSONB)


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    operator_id: Mapped[str] = mapped_column(String)
    upload_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Artifact(Base):
    """Append-only snapshots survive edits to an upload's current state."""

    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    upload_id: Mapped[str] = mapped_column(ForeignKey("uploads.id"))
    kind: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONB)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("collection", "document", "ordinal"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    collection: Mapped[str] = mapped_column(String, index=True)
    document: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB)
    embedding: Mapped[list | None] = mapped_column(Vector(), nullable=True)


engine = create_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
DB = sessionmaker(engine, expire_on_commit=False)
