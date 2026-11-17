# DataBridge

DataBridge is an AI-assisted CSV onboarding application that proposes schema mappings using retrieved policy documentation, validates records deterministically, and imports approved data through transactional, retry-safe workflows.

Built for an operator importing customer files with unfamiliar column names, inconsistent categories and invalid values. Local AI reduces the header/policy lookup work while the operator controls the mapping and import.

![Real local Qwen3 mapping suggestions with policy citations](docs/images/mapping-proposal.png)

**React + TypeScript / FastAPI / PostgreSQL + pgvector / Google ADK / Ollama**

## A concrete import

Northstar is a fictional subscription company. A source file might contain:

```csv
full_name,email_address,joined,plan,country
 Maya Chen ,maya.chen@example.com,2025-01-14,professional,US
Oliver Reed,not-an-email,2025-01-23,pro,GB
```

The operator maps full_name to name, selects YYYY-MM-DD and confirms the documented professional-to-pro pair. Validation trims the name and accepts Maya's record; Oliver's invalid email stays in the rejected-row report. The supplied six-row sample produces **3 accepted and 3 rejected rows** on an empty destination after those explicit transformations.

## How it works

1. Upload a bounded UTF-8 CSV and inspect its original rows.
2. Retrieve relevant schema/policy chunks from PostgreSQL using local query embeddings.
3. Generate a typed mapping proposal with retrieved citations. Reviewer is optional.
4. Edit source choices, category pairs and date format. Null date format explicitly requests human selection.
5. Validate the entire file with Python rules and preview original/transformed values.
6. Approve the exact file, mapping version and validation result, with the valid-rows-only policy.
7. Import accepted records in one transaction. Keep rejected rows available for download.

## Architecture

```mermaid
flowchart LR
    UI[React / TypeScript] --> API[FastAPI]
    API --> Docs[Local embeddings + pgvector retrieval]
    Docs --> ADK[Google ADK Investigator]
    ADK <--> Ollama[Ollama / Qwen3 4B]
    ADK --> Review[Optional Reviewer]
    Review <--> Ollama
    ADK --> Human[Operator edits and review]
    Review --> Human
    Human --> Validate[Deterministic full-file validation]
    Validate --> Approval[Exact version-bound approval]
    Approval --> Import[Transactional idempotent import]
    Import --> DB[(PostgreSQL)]
```

Ollama runs separately on the Windows host. Application services run in Docker. Nomic embeddings run on CPU; generation uses the configured local model. The AI path produces mapping data. Application code owns validation, approval and customer writes.

## Engineering decisions

- **Bounded proposals.** Pydantic permits source selection, trim, explicit dates and category pairs. Generated code and SQL are never executed.
- **Authoritative constraints.** Required/optional status and value rules come from the destination schema. A present optional country must be valid; retrieved prose and model concerns cannot change that rule.
- **Exact approvals.** A mapping/date edit clears validation and approval. Execution rechecks the approved version and file/mapping/validation hashes.
- **Retry-safe writes.** Locks, unique normalized emails, conflict rechecks and persisted idempotency results prevent duplicate effects. Existing customers are rejected rather than updated.
- **Optional Reviewer.** The measured comparison found no final mapping-quality improvement, so Reviewer defaults off. Its advisory concerns remain visible when enabled.
- **Inspectable traces.** Sanitized application inputs, parsed outputs, guards, validator results and nested timings distinguish model behavior from Python enforcement. [Small real trace example](docs/examples/local-mapping-trace.json).

## Quick start

Docker Desktop with its Linux engine and Git are required. The database extension and migrations are applied during API startup. There is no default application account.

### Manual/mock mode

No model download, GPU or cloud account is needed. Mock suggestions use deterministic fixtures and lexical retrieval.

**Bash**

```bash
git clone https://github.com/kaushik945/DataBridge.git
cd DataBridge
cp .env.example .env
docker compose up --build -d
```

**PowerShell**

```powershell
git clone https://github.com/kaushik945/DataBridge.git
cd DataBridge
Copy-Item .env.example .env
docker compose up --build -d
```

For an existing checkout, keep its .env and database volume. Wait for [API health](http://localhost:8000/api/health) to return status ok and mode mock, then run these commands in either shell:

```sh
docker compose exec api python -m app.cli setup-operator --username operator
docker compose exec -T api python -m app.cli ingest
```

The provisioning command securely prompts for a password of at least 12 characters. It runs once for the single operator account. Open **http://localhost:5173**, sign in and upload [northstar-customers.csv](samples/northstar-customers.csv). Inspect suggestions, explicitly select the date format, validate and approve. Prior imports can produce destination-email conflicts.

### Real local AI on Windows

The verified configuration uses an RTX 4050 Laptop GPU with 6 GB VRAM and 16 GB RAM. Hardware-dependent performance and model errors remain visible. Install [Ollama for Windows](https://ollama.com/download/windows), quit any auto-started tray server, then start the repository's loopback-only, cloud-disabled server.

**PowerShell, from the clone**

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-ollama.ps1
ollama pull qwen3:4b
ollama pull nomic-embed-text:v1.5
docker compose -f compose.yaml -f compose.local.yaml up --build -d
docker compose -f compose.yaml -f compose.local.yaml exec -T api python -m app.cli local-diagnostics
docker compose -f compose.yaml -f compose.local.yaml exec -T api python -m app.cli ingest
```

Run start-ollama.ps1 only when its service is stopped. If ollama is not on PATH, use the installed executable shown in [setup](docs/setup.md). Downloads are approximately 2.5 GB and 274 MB. Local mode uses real embeddings and generation, has no remote/mock fallback and needs no AI API key. It has no external AI API charges; hardware and electricity still have costs. A fresh local-only setup also needs the operator provisioning command above.

Reviewer remains optional through LOCAL_REVIEWER=true and an API container recreation. The [setup guide](docs/setup.md) covers networking, model identity, reindexing and shutdown.

### Shutdown

```sh
# Manual/mock profile
docker compose down
# Local profile
docker compose -f compose.yaml -f compose.local.yaml down
```

These commands retain database data. Ollama is a separate process. Adding --volumes to down permanently deletes the selected project's database volume.

## Screens from the running application

The images use an isolated demo account and synthetic CSV data. The mapping screenshot is from real local Qwen3 execution; operator edits precede validation/import. [Open the retrieved policy passage](docs/images/mapping-evidence.png).

| Full-file validation | Accepted/rejected import outcome |
|---|---|
| ![Original and transformed synthetic rows with validation errors](docs/images/validation-preview.png) | ![Completed synthetic import with accepted and rejected counts](docs/images/import-result.png) |

## Tests and measured results

Backend checks use a dedicated databridge_test database. Frontend checks require Node.js 24. Set browser credentials to the account you provisioned, as described in [CONTRIBUTING](CONTRIBUTING.md).

```sh
# Create once
docker compose exec -T db createdb -U databridge databridge_test
docker compose exec -T -e AI_MODE=mock -e ALLOWED_ORIGINS=http://localhost:5173 -e DATABASE_URL=postgresql+psycopg://databridge:local-development-only@db:5432/databridge_test api python -m pytest -q
docker compose exec -T api ruff check app tests
cd frontend
npm ci
npm run format:check
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

PowerShell uses npm.cmd/npx.cmd where execution policy requires it. The browser suite checks that the running API is in mock mode before making suggestions. Real-model tests are explicitly opt-in. CI uses disposable operator credentials, synthetic data and no GPU/private credentials.

Release verification passed 127 backend tests in the local-dependency image, five mock browser workflows, and a separate real local mapping/validation/import capture. A public-files-only clean checkout passed 123 backend tests with four SDK skips, and five browser tests with three opt-in skips. [Verification and evaluation details](docs/evaluation.md).

A frozen, internally authored **16-case synthetic comparison** measured the outputs before operator edits:

| Metric | Fixed header baseline | Investigator | Investigator + Reviewer |
|---|---:|---:|---:|
| Correct source choices | 74/80 | 78/80 | 78/80 |
| Exact mappings under the declared rubric | 14/16 | 5/16 | 5/16 |
| Structured/runtime failures | 0 | 0 | 0 |
| Median suggestion-workflow time | 0.557 ms | 6.326 s | 9.839 s |

AI recovered unfamiliar headers but often left ISO formats unresolved, missed an approved alias and failed to abstain on source ambiguity. Reviewer did not improve final quality. Its initial-review precision was 10/10 and recall 10/13, with every detected issue already flagged by Python. These cases are now seen development/regression material. Citation-ID validity does not establish semantic support.

A separate fixed four-row, two-agent HTTP profile used Qwen3 4B Q4_K_M, 4096 context and the RTX 4050/16 GB Windows host. After one warm-up, three sequential requests took 8.374, 8.068 and 8.086 seconds, median 8.086 seconds. These are observations on that input and warm state. [Methods, per-case results and limits](docs/evaluation.md).

## Scope and limitations

The verified deployment is local. The destination is one fixed customer schema and input is bounded UTF-8 CSV. Models can make semantic mistakes, so human review is mandatory. Slash dates always require operator selection, including individually unambiguous slash values. Latency depends on hardware, process/model initialization, cache state and input. The small synthetic evaluation does not establish broad enterprise accuracy.

Cloud container/Terraform configuration is prepared but cloud generation and deployment remain unverified. No cloud resources or billing are needed for the local profiles. Password reset, retention management and production operations are outside this prototype's current scope.

## Documentation

- [Setup and operating modes](docs/setup.md)
- [Architecture and trust boundaries](docs/architecture.md)
- [Evaluation and debugging case study](docs/evaluation.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Three-minute demo](docs/demo-script.md)
- [Technical interview guide](docs/interview-guide.md)
- [Prepared cloud configuration](docs/deployment.md)
- [Contributing and checks](CONTRIBUTING.md)

## License

A project license has not been selected. Public visibility alone does not grant an open-source license. [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).
