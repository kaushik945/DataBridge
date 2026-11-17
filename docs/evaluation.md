# Evaluation and debugging evidence

Deterministic correctness, mock integration and real-model quality are separate measurements. Published results use synthetic inputs. This release includes sanitized summaries and reproducible source; raw historical requests, authentication state and machine-specific diagnostics remain private local evidence.

## Verification layers

- Backend pytest tests validation, schema optionality, date decisions, scoped findings, approval invalidation, concurrency, rollback and idempotency. The base mock image passes 123 and skips four optional SDK tests; the local-dependency image supports the full 127. Re-run commands are in [CONTRIBUTING](../CONTRIBUTING.md).
- Five mock browser workflows exercise the real UI/API with deterministic suggestions. Mock fixture quality is not model accuracy. Real local browser checks are explicitly opt-in.
- Real local generation, retrieval and approval/import/retry journeys have been run separately. The release screenshots come from an isolated real Qwen3 mapping followed by explicit operator edits, validation and import. The release capture passed against a separate local stack: three records imported, three rejected. Four genuine component screenshots exclude account details.

The broader deterministic evaluator in app.evaluate uses 40 synthetic cases, including five parse failures and the known country regression. Its fixture split labels do not establish unseen real-model performance. It resets only databridge_test. Do not combine it with the separate 16-case experiment.

Release checks also passed frontend Prettier, TypeScript, Vite build, backend Ruff lint/format and pip dependency consistency. The separate SDK-only image passed four tests without cloud credentials. The 40-case mock evaluator completed both variants without runtime failures (35 parseable, five expected parse rejections); these are fixture/integration results. Backend pytest reports one upstream Starlette/AnyIO deprecation warning.

A staged-files-only clean checkout was also built with the README default Compose profile and a new database volume, changing only host ports/origin to avoid the existing app. Operator setup, migrations, ingestion, manual/mock imports and idempotent retries passed without private fixture files. Its backend run passed 123 tests with four optional SDK skips; browser verification passed five with three explicit opt-in skips. The full local-dependency run passed all 127.

## Frozen 16-case comparison

[Predeclared labels/rubric](evaluation/assessment-v1-labels.json) and [sanitized per-case results](evaluation/assessment-v1-summary.json) preserve the first comparison. These internally authored cases were frozen before the run, then informed the Reviewer default. They are now seen development/regression material, not an independent enterprise benchmark. No new held-out real-model evaluation is claimed by this release.

Variants were A: fixed header-alias baseline, B: Investigator, C: Investigator plus Reviewer. Baseline ran first; model variant order alternated by case, sequentially, after one development warm-up. Qwen3 4B Q4_K_M used context 4096, output cap 1400, temperature zero and thinking disabled. Windows RTX 4050 Laptop GPU 6 GB, 16 GB RAM; Nomic v1.5 embeddings ran on CPU. Expected labels were outside prompts/retrieval.

| Metric | Baseline | Investigator | Investigator + Reviewer |
|---|---:|---:|---:|
| Source-column choices | 74/80 | 78/80 | 78/80 |
| Exact mappings under the declared rubric | 14/16 | 5/16 | 5/16 |
| Structured/runtime failures | 0 | 0 | 0 |
| Median function workflow | 0.557 ms | 6325.912 ms | 9838.993 ms |
| Mean function workflow | 0.953 ms | 6262.804 ms | 10977.397 ms |
| Known input/output tokens | 0/0 | 23519/5003 | 62106/8429 |

The exact rubric includes source, trim, explicit date/clarification and category pairs; high source accuracy is insufficient. AI recovered unfamiliar headers but left many ISO formats unresolved, missed starter/basic and failed to abstain on competing-email cases. Both AI variants preserved 3/3 required date clarifications. Raw AI formats were already null in all six slash-date runs, so observed guard interventions were zero; deterministic tests exercise noncompliant guesses.

Mapping citation IDs were valid 86/86 and 98/98. IDs were constrained by the output contract, so this is not semantic evidence accuracy. No nonidentity AI category claims were emitted: that support rate is N/A, not 100%.

Reviewer initial reviews detected 10/13 labeled proposal issues with 10/10 issue precision. All ten were already reported by Python. Across all 17 review calls, precision was 11/11 and recall 11/14. Reviewer added zero incremental detections and missed the one unflagged competing-email issue (incremental precision N/A, recall 0/1). No false mapping alarm appeared on the five correct proposals, but one otherwise valid invalid-tier finding speculated about row numbering without support. All 24 support references resolved; only four were placed in the correct reference bucket. Application normalization handles the misplaced validator IDs. The set showed no final mapping-quality improvement, so Reviewer defaults off.

## Fixed-input latency profile

[Sanitized timings and native provider counters](evaluation/profile-summary.json) describe four synthetic rows with full_name/email_addr/joined_on/plan/country, all dates 03/04/2026, three sampled IN values and one blank beyond the sample. Same model/hardware/context/output settings as above, Reviewer enabled, sequential generation. One request warmed the fresh API process; three subsequent HTTP requests took 8374.308, 8067.842 and 8086.113 ms, median 8086.113 ms. Warm-up took 21374.394 ms. This is n=3 warm observations, not a p95 or a general latency promise.

Spans separately measure retrieval, CPU query embedding, vector search, deterministic checks, agent setup, invocation, HTTP attempts and parsing. Ollama load/prompt/evaluation counters are nested within the HTTP time. Do not sum nested spans as independent elapsed time. Warm client setup and parsing were each under 0.3 ms per call. A separate fresh-process diagnostic exposed import and Pydantic/schema-construction work. Sessions were fresh and isolated. No client reuse or evidence reduction was justified; no performance optimization was made.

Reported workflow token counts sum all recorded agent calls, including bounded revisions/retries. Native usage is recorded per HTTP attempt when available; missing usage is not silently zero. There was no controlled comparison to the earlier 38.002-second incident, whose input, workflow and warm conditions differed.

## Country optionality development regression

The saved final Investigator and Reviewer both claimed optional country must be blank. The authoritative schema, source policy, four retrieved passages and persisted chunk hashes agreed that country was optional. The available original final outputs prove the error existed by the final Investigator stage; absent intermediate outputs prevent identifying the first agent/call that introduced it. No stale or truncated retrieved passage was established as the cause.

The model-facing mapping wire schema lacked structured destination optionality facts. That is an evidenced contract gap, not proof of the model's internal reasoning. The fix supplies authoritative structured facts, full-file validator summaries and typed scoped findings. Deterministic rules accept IN and blank and reject invalid nonempty codes. Retrieved prose/model concerns cannot rewrite them. Two known local reproductions removed the country claim while preserving human slash-date selection. This failure was added to development regressions.

[Sanitized real trace excerpt](examples/local-mapping-trace.json) shows policy chunks, initial/final mapping, the date guard and application findings without session identifiers, cookies, private paths or full prompts. It is a selected development example, not an accuracy estimate.

## Reproduce separately

Use a local-mode stack with ingested knowledge. The assessment writes labels/results to its output directory; retain each run separately. From the repository root:

~~~sh
docker compose -f compose.yaml -f compose.local.yaml exec -T api python -m app.assessment --output-dir /tmp/assessment --freeze-labels
docker compose -f compose.yaml -f compose.local.yaml exec -T api python -m app.assessment --output-dir /tmp/assessment --run
~~~

Copy results from the container to a fresh ignored .local-evidence directory if needed. Current code/model runtime can differ from the historical content digest recorded in the summary; do not assume byte-identical timings or scores.

For the fixed HTTP profile, set E2E_USERNAME/E2E_PASSWORD securely as in CONTRIBUTING, enable LOCAL_REVIEWER=true and recreate the API, then run node scripts/profile-local.mjs .local-evidence/profile-new.json from the root. It creates four uploads against localhost:5173 and writes sensitive raw traces locally. Restore Reviewer false afterward. profile-initialization.py and the local smoke scripts are diagnostics, not additional quality evidence.

## Limits

The labels are internally authored, synthetic and small. Case ordering, warm caches, model/runtime versions and hardware affect latency. Citation checks are constrained and semantic scoring covers a narrow oracle. Human time savings, production workloads, independent unseen generalization and deployed cloud behavior have not been established. Full raw historical traces/source archives are preserved locally but deliberately excluded from the public repository.
