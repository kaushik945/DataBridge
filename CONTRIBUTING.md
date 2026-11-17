# Contributing

Use the existing React/TypeScript and FastAPI architecture. Keep AI proposals separate from authoritative rules and human-approved imports. See [setup](docs/setup.md) before changing code. No license has been selected; discuss reuse/contribution terms with the repository owner.

## Local checks

Start the README's mock stack, provision an operator, ingest documents, and create the dedicated test database once:

~~~sh
docker compose exec -T db createdb -U databridge databridge_test
docker compose exec -T -e AI_MODE=mock -e ALLOWED_ORIGINS=http://localhost:5173 -e DATABASE_URL=postgresql+psycopg://databridge:local-development-only@db:5432/databridge_test api python -m pytest -q
docker compose exec -T api ruff check app tests
docker compose exec -T api ruff format --check app tests
cd frontend
npm ci
npm run format:check
npm run typecheck
npm run build
npx playwright install chromium
~~~

The base image intentionally skips four optional SDK tests. Build the local override to run all 127 tests; keep AI_MODE=mock on the test process so deterministic tests do not call Ollama. Tests/evaluation must never target the application database. Use npm.cmd/npx.cmd on PowerShell where required.

Browser checks use the provisioned account. Enter the password without a shell-history literal:

~~~powershell
$env:E2E_USERNAME = 'operator'
$credential = Get-Credential -UserName $env:E2E_USERNAME -Message 'Local test operator'
$env:E2E_PASSWORD = $credential.GetNetworkCredential().Password
npm.cmd run test:e2e
Remove-Item Env:E2E_PASSWORD, Env:E2E_USERNAME
~~~

For Bash, from frontend:

~~~bash
export E2E_USERNAME=operator
read -rs -p 'Local operator password: ' E2E_PASSWORD; echo
export E2E_PASSWORD
npm run test:e2e
unset E2E_PASSWORD E2E_USERNAME
~~~

The default browser suite has five mock workflows; two real-model tests and the public-image capture are explicitly skipped. Set E2E_BASE_URL for a different local browser origin. Real local tests require a local-mode stack, ingested local embeddings, E2E_LOCAL=1 and actual credentials. Read the relevant test before opting in; they create synthetic records.

For an isolated stack, use docker compose -p databridge-check -f compose.smoke.yaml up --build -d. It uses ports 5273/8100, an independent database volume and no .env/private credential dependency. Use the same project/file arguments for all exec/down commands, E2E_BASE_URL=http://localhost:5273 for browser checks, and the backend origin override shown above. Adding compose.local.yaml enables real local inference for that isolated project. Do not run two smoke projects on the same host ports simultaneously.

## Evaluation and traces

Mock integration evaluation is separate from real-model quality:

~~~sh
docker compose exec -T -e AI_MODE=mock -e DATABASE_URL=postgresql+psycopg://databridge:local-development-only@db:5432/databridge_test api python -m app.evaluate --output /tmp/evaluation.json
~~~

It resets only databridge_test and runs no paid inference. [Evaluation](docs/evaluation.md) documents the frozen development set and real-model commands. Store new raw results in ignored .local-evidence or .tools directories; sanitize deliberately before publication. Do not overwrite historical evidence or relabel a seen regression as unseen held-out validation.

CI runs mock backend/evaluation/browser checks plus a separate optional-SDK image test. It requires no private credentials, GPU or cloud account. Keep real-model checks opt-in. Add focused deterministic regression tests when changing validation, approvals, idempotency or agent contracts. Run formatters on files you change and include actual checks/limitations in the pull request.

## Publication hygiene

Do not commit .env, generated operator files, cookies, private uploads, raw traces, database dumps, model weights or local caches. Use synthetic data and harmless example placeholders. Review staged files and git diff --cached --check before committing. Cloud configuration is prepared and unverified; local development does not authorize provisioning resources.
