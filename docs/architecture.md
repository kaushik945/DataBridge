# Architecture

DataBridge separates AI proposals from application-controlled validation, approval and import. [agents.py](../backend/app/agents.py) runs Google ADK with an Investigator and an optional sequential Reviewer. Neither agent has an import, approval, shell or SQL tool. Local Qwen3 generation is served by Windows Ollama; Nomic CPU query embeddings feed pgvector retrieval.

~~~mermaid
flowchart LR
    Human[Operator] --> UI[React / TypeScript]
    UI --> API[FastAPI / session + CSRF]
    API --> PG[(PostgreSQL + pgvector)]
    API --> Retrieval[Policy retrieval]
    Retrieval --> AI[ADK Investigator / optional Reviewer]
    AI <--> Ollama[Local Ollama]
    AI --> UI
    UI --> Rules[Python validation]
    Rules --> Approval[Exact version approval]
    Approval --> Import[Locked transaction / idempotency]
    Import --> PG
~~~

## Code and persistence

- [domain.py](../backend/app/domain.py): typed rules, authoritative schema facts, transformations, validation and safe CSV reports.
- [review.py](../backend/app/review.py): scoped typed findings, full-file validator summaries and application-derived review status.
- [main.py](../backend/app/main.py): authenticated workflow, ownership, versioned artifacts, approval and transactional import.
- [models.py](../backend/app/models.py): operators/sessions, uploads, mappings, customers, idempotency requests, audit events, chunks and immutable artifacts.
- [retrieval.py](../backend/app/retrieval.py) and [local_provider.py](../backend/app/local_provider.py): collection-isolated ingestion, cosine retrieval, endpoint restrictions and local transports.

An upload retains parsed original values, physical ending-line numbers, original-byte hash and immutable workflow snapshots. GCS archival is optional and unverified in the cloud. The database contains customer data and requires operational retention/backup decisions.

## State and import correctness

UPLOADED -> NEEDS_REVIEW -> VALIDATED -> APPROVED -> IMPORTED.

Saving a mapping creates a version and clears validation/approval. Revalidation clears approval too. Approval binds operator, timestamp, file hash, mapping version/hash, validation hash and valid-only policy. Import accepts the approval identity, never arbitrary transformed rows. Imported uploads are terminal.

Mutations lock the upload. Import locks the idempotency key, upload and destination-write advisory lock, then rechecks state/conflicts. Customers, result and audit commit atomically. Matching retries return the persisted result; a different fingerprint is rejected. Unique normalized emails protect against outside writers. A late integrity conflict rolls back all inserts, invalidates approval and requires revalidation.

## Schema and model boundaries

Required/optional status and allowed values come from Python, are supplied as structured facts to both agents and cannot be overridden by retrieved prose. Optional country_code accepts absence; a present value must still pass the code's ISO validation. Documentation/schema conflicts surface separately for correction. Models only propose the supported typed transformations; they never execute arbitrary code.

Slash-containing date sources require an explicit human format decision. The guard clears AI-selected slash formats. A null format means clarification, not permission to infer. Row format failures are validation errors rather than incorrect source-column mappings. Changes to date transformation invalidate approval just like other mapping edits.

Findings carry field, issue type, severity, explanation, scope, evidence/validator support, origin and blocking status. Deterministic validation errors and required human choices can block; unsupported model concerns remain advisory. Sample findings cannot claim inspection of all rows. ready_for_human still requires operator review.

## Retrieval and observability

Knowledge Markdown splits at second-level headings and retains document/title/heading, ordinal, hash and content-derived chunk ID. Ingestion replaces changed/deleted content atomically within its collection. Mock uses lexical ranking; local uses Nomic embeddings and pgvector cosine distance. The small corpus uses exact search. A valid citation ID proves existence, not semantic support.

Agent samples redact names, emails, notes and unknown values; only bounded date/tier/country samples accompany headers. Retrieved text and headers remain untrusted. Trace artifacts capture sanitized inputs, typed output, bounded attempts, findings and usage. Monotonic spans distinguish queue, retrieval, embeddings/search, setup, model HTTP and parsing. Native Ollama timing is nested in request time and must not be added again. Token totals sum recorded calls, including revisions/retries when reported; missing provider usage stays unknown.

## Security and scope

Sessions use random HttpOnly, SameSite Strict cookies; COOKIE_SECURE enables HTTPS-only cookies. Authenticated writes require CSRF and an exact allowed origin. Login is throttled in the database. Caller-supplied forwarded addresses are ignored. Upload resources require ownership. All data/evidence/report endpoints require authentication.

Defaults bound uploads to 5 MB, 10,000 rows and 50 columns. Request body and mapping bounds are enforced separately. Nginx adds a request limit. Reports escape spreadsheet-formula prefixes. The application is a local synchronous prototype; retention, session cleanup, password recovery and production operations remain limitations. [Engineering decisions](decisions.md), [evaluation](evaluation.md).
