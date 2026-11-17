# Troubleshooting

## Docker Linux-engine pipe is missing

The dockerDesktopLinuxEngine named-pipe error means the CLI cannot reach Docker Desktop's Linux daemon. Start Docker Desktop, wait until its engine reports running and run docker info. Ensure Linux containers and the intended Docker context are selected. Then rerun the README Compose command. Changing the Compose file will not start the daemon.

## API is unavailable or migrations fail

Run docker compose ps and docker compose logs api db using the same profile arguments as startup. Wait for the database health check and API migrations. The app is on port 5173, API on 8000; the isolated smoke stack uses 5273/8100. A host-port conflict requires stopping the owning service or intentionally choosing a separate stack. Do not delete an existing database to fix an unrelated connectivity issue.

If the database password changed after initial volume creation, editing POSTGRES_PASSWORD does not update the existing database account. Restore the matching configuration or deliberately rotate that account. Retain the volume and backups.

## Login or origin failures

Provision the operator once with the CLI and use its actual password. Generated .local-operator.json is not needed for normal setup. Keep the browser origin consistent with ALLOWED_ORIGINS; localhost and 127.0.0.1 are distinct origins. Tests use the fixture origin http://localhost:5173 even when the isolated browser stack uses 5273, so the documented backend command overrides only that test process. Do not disable CSRF/origin checks.

## Ollama/local-model failure

Check http://127.0.0.1:11434/api/version, the downloaded models and the local-diagnostics command. Quit a conflicting tray server before the repository startup script; the script intentionally refuses to replace it. Check .tools/ollama.stderr.log locally without publishing prompts/paths. Docker Desktop must reach host.docker.internal:11434. Local mode has no cloud/mock fallback.

If GPU inference is unavailable, inspect Windows GPU visibility and Ollama's runtime diagnostics. CPU execution can be much slower. No particular hardware latency is guaranteed. Nomic embeddings intentionally use CPU. An empty retrieval collection needs local-profile ingestion, not a model change.

## Mapping/validation is blocked

Read field-specific findings and full-file validator results. A sample-based model concern is advisory. Optional country may be blank; a present code still must be valid. Slash dates require an explicit human format. ISO rejects slash input, and impossible calendar dates remain row errors. Saving edits or revalidating clears previous approval. Correct the mapping and validate again.

## Test skips and missing dependencies

The base mock image omits optional Google ADK/local SDK checks: skipped is not passed. Build the local override for the full backend dependency set. Real-model browser checks require explicit opt-in and provisioned credentials. Normal CI needs no GPU. See [CONTRIBUTING](../CONTRIBUTING.md) and [evaluation](evaluation.md).
