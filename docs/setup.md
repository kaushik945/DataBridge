# Setup and operating modes

The verified path is Docker Desktop with Linux containers on Windows and Node.js 24 for development checks. Docker Compose v2 builds the frontend/API and starts PostgreSQL 16 with pgvector. Database migrations run when the API starts. No cloud account is required.

## Fresh manual/mock setup

Follow the clone, environment copy, startup and operator provisioning commands in the [README](../README.md#quick-start). The app is at http://localhost:5173; API health is at http://localhost:8000/api/health. The only required configuration is the committed example copied to an ignored .env. Its database password is a harmless loopback-development default, not a production secret. If you change it, update POSTGRES_PASSWORD and DATABASE_URL together before creating the database volume.

The CLI securely prompts for a 12-character minimum operator password. Version 1 supports a single account; a second setup attempt refuses to replace it. No generated credential file is required. SETUP_PASSWORD is an alternative for disposable automated checks; avoid plaintext shell-history literals. Application authentication uses cookies and CSRF tokens, not an AI API key.

Compose runs Alembic automatically. The ingest command reads the shipped docs/knowledge directory and writes the selected retrieval collection. In mock mode it uses lexical fixtures; this is useful for UI/import verification and is not real-model accuracy evidence.

## Windows local AI

Ollama runs on the Windows host, separately from Docker. The [startup script](../scripts/start-ollama.ps1) detects its standard per-user install or an ignored .tools/ollama installation. It stores model weights/logs in .tools, binds 127.0.0.1:11434, disables cloud, limits generation concurrency to one and uses a 4096-token context.

Quit the tray server before using the script. The script refuses to replace a running server. After starting it, wait for http://127.0.0.1:11434/api/version, then pull the two models using the README commands. If Ollama is absent from PATH, PowerShell can use its standard installed executable:

~~~powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:4b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull nomic-embed-text:v1.5
~~~

The local Compose override installs the optional local dependencies and selects AI_MODE=local. Docker Desktop routes host.docker.internal:11434 to the separately running service. This route was verified on the development host; do not expose Ollama publicly to solve a networking issue. Other operating systems/network configurations are not verified.

Run local-diagnostics, then ingest in the local profile. Nomic v1.5 query/document prefixes, dimensions and model digest form the collection identity. Changed documents are replaced atomically during ingestion; changed model identity uses a separate collection. Re-run ingestion after changing policy files or embedding configuration. Empty/wrong collections cause an explicit failure; local mode never silently falls back to mock or cloud.

Reviewer defaults off. To enable it in PowerShell:

~~~powershell
$env:LOCAL_REVIEWER = 'true'
docker compose -f compose.yaml -f compose.local.yaml up -d --no-deps api
~~~

Set it to false and recreate the API again to restore the default. Remove the shell variable afterward. A fresh process/model may need a warm-up before a timed demonstration. Qwen3 generation uses the GPU when available; Nomic embedding requests explicitly use CPU.

## Sample contract

Upload [northstar-customers.csv](../samples/northstar-customers.csv). Confirm name/full_name, email/email_address, signup_date/joined, subscription_tier/plan and country_code/country. Keep name trimming enabled, select YYYY-MM-DD and use these tier pairs:

~~~json
{"starter":"basic","professional":"pro","business":"enterprise"}
~~~

On an empty destination, three rows pass and three fail: invalid email, impossible calendar date and a within-file duplicate normalized email. Repeated imports can add destination conflicts. [ambiguous-dates.csv](../samples/ambiguous-dates.csv) requires a human slash-date order choice. Choosing YYYY-MM-DD rejects 03/04/2026; it does not guess.

## Persistence and shutdown

Compose down stops the selected project's containers and retains its database volume. Use the same profile arguments used for startup. Do not add --volumes unless you intend to permanently delete that project's data. Ollama is separate; stop the script-started process when you no longer need it. Keep .env, uploads, operator passwords, authentication state and model weights out of Git.

For isolated checks, compose.smoke.yaml uses 5273/8100 and its own volume. See [CONTRIBUTING](../CONTRIBUTING.md). The verified release did not require private fixtures, a generated operator file or existing application data.
