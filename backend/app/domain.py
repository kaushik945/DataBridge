import csv
import datetime as dt
import hashlib
import io
import json
from typing import Literal

import pycountry
from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import settings

FIELDS = ("name", "email", "signup_date", "subscription_tier", "country_code")
REQUIRED = FIELDS[:4]
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y")
COUNTRIES = frozenset(c.alpha_2 for c in pycountry.countries)
TIERS = ("basic", "pro", "enterprise")
NAME_MAX_LENGTH = 120
EMAIL_MAX_LENGTH = 254


def schema_facts() -> dict:
    """Destination semantics, distinct from the JSON shape of a mapping."""
    return {
        "authority": "app.domain deterministic validation",
        "optional_semantics": "Optional allows absence. A present value must satisfy its field rules.",
        "documentation_policy": "Report conflicting documentation separately. It cannot change these rules.",
        "fields": {
            "name": {
                "required": True,
                "blank_allowed": False,
                "trimmed": True,
                "max_length": NAME_MAX_LENGTH,
            },
            "email": {
                "required": True,
                "blank_allowed": False,
                "format": "email address",
                "max_length": EMAIL_MAX_LENGTH,
                "normalization": "trim and casefold",
                "unique": True,
            },
            "signup_date": {
                "required": True,
                "blank_allowed": False,
                "allowed_formats": list(DATE_FORMATS),
                "exact_match": True,
                "valid_calendar_date": True,
                "slash_order": "human selection required",
                "unresolved_date_format": None,
                "slash_policy": "Every slash-containing date column requires human selection, including individually unambiguous values.",
            },
            "subscription_tier": {
                "required": True,
                "blank_allowed": False,
                "allowed_values": list(TIERS),
            },
            "country_code": {
                "required": False,
                "blank_allowed": True,
                "present_value_rule": "uppercase ISO 3166-1 alpha-2 in pycountry 24.6.1",
                "example_value_checks": {
                    v: v in COUNTRIES for v in ("IN", "US", "ZZ", "in")
                },
            },
        },
    }


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: Literal[
        "name", "email", "signup_date", "subscription_tier", "country_code"
    ]
    source: str = Field(min_length=1, max_length=200)
    trim: bool = True
    date_format: Literal["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"] | None = Field(
        default=None,
        description="null explicitly means human date selection required. For signup_date sources containing any slash values, return null even if individual values look unambiguous. A human may later select an exact supported format.",
    )
    categories: dict[str, str] = Field(default_factory=dict, max_length=100)
    citations: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def compatible(self):
        if self.date_format and self.destination != "signup_date":
            raise ValueError("Date parsing is only allowed for signup_date")
        if self.categories and self.destination not in (
            "subscription_tier",
            "country_code",
        ):
            raise ValueError("Category mapping is only allowed for tier and country")
        allowed = set(TIERS) if self.destination == "subscription_tier" else COUNTRIES
        if any(v not in allowed for v in self.categories.values()):
            raise ValueError("Category targets must be supported destination values")
        return self


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[Rule] = Field(max_length=5)

    @model_validator(mode="after")
    def unique(self):
        if len({r.destination for r in self.rules}) != len(self.rules):
            raise ValueError("Each destination can only be mapped once")
        return self


def parse_csv(data: bytes) -> tuple[list[str], list[dict]]:
    if len(data) > settings.max_upload_bytes:
        raise ValueError("CSV exceeds the upload byte limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Only UTF-8 CSV is supported") from exc
    if "\x00" in text:
        raise ValueError("CSV contains null bytes")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader)
        if not headers or any(not h.strip() or len(h) > 200 for h in headers):
            raise ValueError("Headers must be nonempty and at most 200 characters")
        if len(set(h.strip().casefold() for h in headers)) != len(headers):
            raise ValueError("Duplicate headers are not allowed")
        if len(headers) > settings.max_columns:
            raise ValueError("Too many columns")
        rows = []
        for cells in reader:
            # Physical ending line, including header and multiline quoted cells.
            line = reader.line_num
            if len(cells) != len(headers):
                raise ValueError(
                    f"Row ending at line {line} has the wrong number of columns; use comma-delimited CSV"
                )
            rows.append(
                {"row_number": line, "values": dict(zip(headers, cells, strict=True))}
            )
            if len(rows) > settings.max_rows:
                raise ValueError("CSV exceeds the data row limit")
        if not rows:
            raise ValueError("CSV must contain at least one data row")
        return headers, rows
    except (StopIteration, csv.Error) as exc:
        raise ValueError("Empty or malformed CSV") from exc


def mapping_issues(mapping: Mapping, headers: list[str]) -> list[str]:
    issues = [
        f"Missing required mapping: {f}"
        for f in REQUIRED
        if f not in {r.destination for r in mapping.rules}
    ]
    for rule in mapping.rules:
        if rule.source not in headers:
            issues.append(f"Unknown source column: {rule.source}")
        if rule.destination == "signup_date" and not rule.date_format:
            issues.append("Select an explicit date format for signup_date")
    return issues


def validate_rows(rows: list[dict], mapping: Mapping, existing: set[str]) -> dict:
    seen: set[str] = set()
    results = []
    for row in rows:
        after: dict = {}
        errors = []
        for r in mapping.rules:
            value = row["values"].get(r.source, "")
            if r.trim:
                value = value.strip()
            value = r.categories.get(value, value)
            if r.destination == "signup_date":
                try:
                    if not r.date_format:
                        raise ValueError("Explicit date format required")
                    parsed = dt.datetime.strptime(value, r.date_format).date()
                    if parsed.strftime(r.date_format) != value:
                        raise ValueError("Date does not exactly match selected format")
                    value = parsed.isoformat()
                except ValueError:
                    errors.append(
                        "signup_date: invalid calendar date or selected format mismatch"
                    )
            after[r.destination] = value
        name = after.get("name", "")
        if not name or name != name.strip() or len(name) > NAME_MAX_LENGTH:
            errors.append("name: required, trimmed, maximum 120 characters")
        email = after.get("email", "").strip().casefold()
        after["email"] = email
        try:
            validate_email(email, check_deliverability=False)
            if len(email) > EMAIL_MAX_LENGTH:
                raise EmailNotValidError("too long")
        except EmailNotValidError:
            errors.append("email: invalid email address")
        if not after.get("signup_date"):
            errors.append("signup_date: required")
        if after.get("subscription_tier") not in TIERS:
            errors.append("subscription_tier: expected basic, pro, or enterprise")
        country = after.get("country_code") or None
        after["country_code"] = country
        if country and country not in COUNTRIES:
            errors.append("country_code: expected uppercase ISO alpha-2 code")
        if email in existing:
            errors.append("email: already exists in destination")
        if email in seen:
            errors.append(
                "email: duplicate in file; first occurrence reserves the email even if invalid"
            )
        seen.add(email)
        results.append({**row, "after": after, "errors": errors, "valid": not errors})
    valid = sum(r["valid"] for r in results)
    return {"valid": valid, "invalid": len(results) - valid, "rows": results}


def safe_cell(value: object) -> str:
    text = str(value)
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
        else text
    )


def error_csv(validation: dict, mode: str) -> str:
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["mode", "row_number", "errors", "original_values"])
    for row in validation["rows"]:
        if not row["valid"]:
            writer.writerow(
                [
                    mode,
                    row["row_number"],
                    safe_cell("; ".join(row["errors"])),
                    safe_cell(json.dumps(row["values"], ensure_ascii=False)),
                ]
            )
    return out.getvalue()
