# Evaluation and debugging evidence

Deterministic correctness, mock integration and real-model quality are separate measurements. Published results use synthetic inputs. This release includes sanitized summaries and reproducible source; raw historical requests, authentication state and machine-specific diagnostics remain private local evidence.

## Category preview comparison

The category evaluation uses five labeled synthetic cases: an unfamiliar header, three approved aliases together, a case-sensitive alias with a blank, canonical-only tiers, and undocumented values. The labels require exact policy pairs for the selected source and no transformations for unsupported values. This is development evidence. [Per-case results](evaluation/category-comparison.json).

| Five local cases | Correct alias pairs | Proposals rejected by Python | Human source edits | Human pair edits | Model calls | Median workflow |
|---|---:|---:|---:|---:|---:|---:|
| Mapping Agent + documented lookup | 5/5 | 0 | 5 | 0 | 5 | 11.90 s |
| Single agent + profile and preview | 5/5 | 10 | 0 | 0 | 8 | 11.75 s |
| Conditional Mapping + Category agents | 5/5 | 0 | 5 | 0 | 8 | 12.52 s |

The lookup uses zero model calls for alias selection. The calls in its row are for finding the source columns. The single agent receives eligible profiles upfront, uses the same retrieved policy and can refine once using the same Python feedback. The conditional workflow profiles the selected source after mapping and spends its extra three calls on the three files with documented aliases. It skipped both the canonical and unsupported-only files. All three approaches selected the labeled tier source in every case. Source edits count differences across destination assignments. Pair edits count changes to accepted category plans after the Python checks. Human date selection and disposition of unresolved input are common to all three and excluded from those edit counts. Zero unsupported pairs reached the editable plans. The ten single-agent rejections are credited to Python.

One separate warm-up preceded the 15 measured workflows with rotated variant order. Measurements cover retrieval, model calls and the read-only preview in the backend process. Ollama 0.40.16 served Qwen3 4B Q4_K_M with 4096 context and a 1400-token output cap on a Windows RTX 4050 Laptop GPU with 6 GB VRAM and 16 GB of system RAM. Nomic v1.5 embeddings ran on CPU. Each variant has five timings. These medians do not establish a general latency ranking.

Use deterministic documented lookup as the recommended default for this exact-match alias policy. It matched the conditional agent on supported pairs, produced zero unsupported proposals and used three fewer model calls. The conditional workflow was active for that comparison and exposed its skip reasons and preview. The generalist experiment needed fewer column corrections on this set. Its ten rejected proposals show why exact policy checks matter even when the accepted results look identical.

In the real Chromium demo, the Mapping Agent selected membership_band, and the category agent proposed professional to pro with a valid policy citation. Python counted two affected rows and one unresolved gold row. Changing the pairs recomputed the preview. The operator confirmed the sources, removed an unnecessary optional country assignment and selected DD/MM/YYYY. Validation and approval imported three records and rejected one. The workflow took 13.882 s (11.593 s mapping, 1.271 s category). A canonical-only copy used one Mapping Agent call and took 11.088 s. These are separate demo observations.

To rerun against a local stack with ingested policies:

~~~sh
docker compose -f compose.yaml -f compose.local.yaml exec -T api python -m app.category_evaluation --output /tmp/category-evaluation.json
~~~

The harness reads policies and uses synthetic in-memory rows. It leaves uploads and customer records untouched.

## Source assignment audit

The original five-case artifact preserved final tier selections and edit/rejection counts. Its local copy is byte-identical. It omitted initial mappings, non-tier assignments, per-call feedback and individual rejected pairs. The trace below comes from a new local replay. It reproduced the original per-case counts and tier selections. [Original results](evaluation/category-comparison.json) and [diagnostic replay traces](evaluation/category-source-replay.json).

All three workflows use one source scorer. For the five known cases, the expected assignments are name to name, email to email, signup_date to joined, subscription_tier to the labeled tier header and country_code unset. Each mismatched destination costs one edit. An unexpected optional assignment counts even when the tier assignment is correct. Date transforms and alias pairs are scored separately. The replay shows that all ten source edits were unnecessary country assignments. The two lookup/delegation workflows initially mapped country_code to name in four cases and package in the case-sensitive case. The single agent left country_code unset on its first call.

| Known case | Workflow | Expected tier source | Initial tier source | Final tier source | Preview feedback sent to a model | Human source edit |
|---|---|---|---|---|---|---|
| Unfamiliar | Mapping + lookup | membership_band | membership_band | membership_band | None | Remove country_code mapped to name |
| Unfamiliar | Single agent | membership_band | membership_band | membership_band | 0 accepted, 1 rejected. Remaining professional | None |
| Unfamiliar | Conditional agents | membership_band | membership_band | membership_band | None | Remove country_code mapped to name |
| Three aliases | Mapping + lookup | plan | plan | plan | None | Remove country_code mapped to name |
| Three aliases | Single agent | plan | plan | plan | 0 accepted, 1 rejected. Remaining business, professional, starter | None |
| Three aliases | Conditional agents | plan | plan | plan | None | Remove country_code mapped to name |
| Case-sensitive | Mapping + lookup | package | package | package | None | Remove country_code mapped to package |
| Case-sensitive | Single agent | package | package | package | 0 accepted, 3 rejected. Remaining starter, with citation failure | None |
| Case-sensitive | Conditional agents | package | package | package | None | Remove country_code mapped to package |
| Canonical only | Mapping + lookup | membership_band | membership_band | membership_band | None | Remove country_code mapped to name |
| Canonical only | Single agent | membership_band | membership_band | membership_band | None | None |
| Canonical only | Conditional agents | membership_band | membership_band | membership_band | None | Remove country_code mapped to name |
| Unsupported only | Mapping + lookup | plan | plan | plan | None | Remove country_code mapped to name |
| Unsupported only | Single agent | plan | plan | plan | None | None |
| Unsupported only | Conditional agents | plan | plan | plan | None | Remove country_code mapped to name |

The single agent's ten rejections all occurred in its **initial** category output. Its first schema returns a column mapping and a category plan. The next call, when needed, uses a schema with only category pairs and unresolved values. The application applies those pairs to the already selected column. The rejections therefore could change the alias plan but could not change the country or tier source. The initial prompt also differed in profiles, output schema and instructions, so the known replay does not isolate which input caused the optional country omission.

| Known case | Rejections | Initial rejected proposals and reasons |
|---|---:|---|
| Unfamiliar | 1 | membership_band to subscription_tier treated the column header as a row value |
| Three aliases | 1 | plan to subscription_tier treated the column header as a row value |
| Case-sensitive | 3 | starter to basic used the long chunk ID rather than the supplied short alias reference P1. professional to pro and business to enterprise proposed values absent from the column |
| Canonical only | 4 | name to name, email to email, joined to signup_date, and membership_band to subscription_tier were emitted as category pairs despite an empty eligible alias profile |
| Unsupported only | 1 | plan to subscription_tier was emitted as a category pair despite an empty eligible alias profile |

The rejection counter also had a scope asymmetry. It charged the single agent for pairs emitted inside mapping rules, while the other workflows silently discarded equivalent out-of-scope output. The scorer now counts these consistently for all variants. It records source differences and the reason for each edit alongside the initial and final maps.

The corrected rerun preserved every initial and final source choice and all five correct alias pairs per workflow. It counted zero pairs emitted inside mapping rules across the 15 workflows, so the scoring fix itself did not change the totals. The single agent emitted different proposals in the three-alias case. Its initial output changed from one rejected header-to-field pair to three rejected alias pairs with unsupported citations or targets. This raised its rejection count from 10 to 12, with all three alias pairs repaired on that case's category-only refinement. [Corrected rerun traces](evaluation/category-source-corrected.json).

The proposed mapping retry was conditional on the single agent using feedback to fix a source. The audit did not show that behavior. The fresh experiment instead gives the Mapping Agent deterministic coverage counts before its first call and keeps alias application deterministic. No source retry is introduced.

## Fresh source selection comparison

The eight fresh synthetic cases have separate labels for the selected tier source or intended abstention. They cover misleading headers, clearly competing columns, close or equal coverage, weak coverage, and unambiguous canonical and alias controls. Each file has a labeled country source. The five known cases were used for debugging.

The comparison includes the conditional agents used by the API, the same Mapping Agent with deterministic alias lookup, and an experimental lookup variant that gives the Mapping Agent per-column counts up front. The profile counts exact canonical tiers and unambiguous documented aliases over all rows after trimming. A strong candidate needs at least two matching rows, coverage of at least two-thirds of all rows, and a lead of at least 25 percentage points over the runner-up. The experiment accepts a tier assignment only when the model and the profile agree. Close, tied and weak cases require operator review. The API used conditional delegation for this historical run.

| Eight fresh cases | Correct assigned tiers | Correct abstentions | Required source edits | Model calls | Median workflow |
|---|---:|---:|---:|---:|---:|
| Former default, conditional agents | 2/5 | 1/3 | 5 | 10 | 12.80 s |
| Mapping Agent + lookup | 2/5 | 1/3 | 5 | 8 | 12.09 s |
| Mapping Agent with upfront profiles + lookup | 4/5 | 3/3 | 1 | 8 | 12.19 s |

All five edits in each unprofiled workflow affected the tier field. The profile variant made one mapping call per case, two fewer calls in total than the former default. Compared with plain lookup, upfront profiling added no calls and the measured median was 98 ms higher. Across the five labeled assigned columns, it recovered 7/8 expected alias pairs versus 2/8 for each unprofiled workflow. The remaining edit was the billing-plan decoy. The profile identified benefit_code with 3/3 supported rows, the model still chose plan, and the guard left it unresolved. [Fresh per-case traces](evaluation/category-source-fresh.json).

| Fresh case | Expected final tier source | Former default | Plain lookup | Profile + lookup |
|---|---|---|---|---|
| Billing plan decoy | benefit_code | plan | plan | Human review |
| Misleading membership band | bundle_level | membership_band | membership_band | bundle_level |
| Clearly competing headers | plan | Human review | Human review | plan |
| Close coverage | Human review | tier | tier | Human review |
| Equal coverage | Human review | Human review | Human review | Human review |
| Weak coverage | Human review | tier | tier | Human review |
| Canonical control | plan | plan | plan | plan |
| Unfamiliar control | access_level | access_level | access_level | access_level |

**Before and after on misleading_band.** The labeled source was bundle_level. Under the former default, the Mapping Agent chose membership_band. Its geographic values had no documented aliases, so delegation skipped, the wrong source stayed selected, and the 14.217 s workflow required one correction. With the upfront profile, membership_band had 0/3 supported rows and bundle_level had 3/3, all documented aliases. The Mapping Agent chose bundle_level on its first call. Deterministic lookup applied starter to basic, professional to pro and business to enterprise, affecting three rows. This run took 14.819 s and required zero source edits. Both runs made one model call, with no preview feedback sent to either model.

Both benchmark suites run sequentially after a separate warm-up and rotate variant order. The read-only harness uses the same final source scorer in all variants. Expected abstentions count as correct workflow decisions and still require human review. The timing covers the full backend workflow including retrieval, profiling, inference and final preview.

~~~sh
docker compose -f compose.yaml -f compose.local.yaml exec -T api python -m app.category_evaluation --suite known --output /tmp/category-known.json
docker compose -f compose.yaml -f compose.local.yaml exec -T api python -m app.category_evaluation --suite fresh --output /tmp/category-fresh.json
~~~

## Promoting upfront profiles

The original eight-case comparison used the shared category evaluator and a local Qwen3 4B model with 4096 context, 1400 output tokens, temperature zero and thinking disabled. The conditional branch used category_strategy=agent. Plain lookup used category_strategy=lookup. The experimental profile branch used that same lookup strategy with an evidence payload computed by the evaluator and a guard that required agreement with the strongest candidate. The scorer compared the final source with the label for each destination. A wrong source, a missing expected assignment or an unexpected assignment each counted as one inferred edit. These are label-derived counts without observed operator corrections.

The billing-plan decoy had a unique candidate. benefit_code contained two canonical rows and one documented alias, while plan contained billing cadence and had zero tier matches. The historical profile named benefit_code, and the model still returned plan. The source guard withheld plan. The failure was a wrong model choice despite a strong candidate. The earlier profile dropped zero-count columns, so it did not show plan's zero explicitly. The promoted workflow passes these negative counts within the bounded profile and keeps the full column-mapping instructions first. A first draft that put the tier instruction first produced tier-only outputs on two original cases and was superseded before its fresh-case results were inspected.

The normal suggest endpoint now computes the profile inside the production workflow and uses deterministic documented aliases. It still requires a unique strong candidate and agreement with the model. The full-file counts are ranked before clipping to 12 entries. Lookup uses the same trimming convention as profiling. Weak, tied and contradictory selections stay open for operator review. Conditional category calls remain available as an explicit configuration and benchmark variant.

The follow-up used the same local model settings and scoring for both lookup variants. Each suite ran sequentially after warm-up and alternated which variant went first. Timings include retrieval, mapping and the read-only preview. The new cases were labeled before the final run. They cover an invoice cadence decoy, conflicting tier-like headers with different coverage, an equal-coverage tie, a canonical-only control and weak evidence that calls for human selection.

| Set | Lookup workflow | Correct tier decisions | Label-inferred source edits | Model calls | Median workflow |
|---|---|---:|---:|---:|---:|
| Original eight, replay | Plain lookup | 3/8 | 5 | 8 | 12.21 s |
| Original eight, replay | Upfront profiles + lookup | 8/8 | 0 | 8 | 11.89 s |
| Five fresh cases | Plain lookup | 1/5 | 4 | 5 | 13.89 s |
| Five fresh cases | Upfront profiles + lookup | 5/5 | 0 | 5 | 12.55 s |

On the fresh cases, profiled lookup picked all three labeled tier columns and correctly left both review cases open. It applied all three expected alias pairs. Plain lookup picked the canonical control correctly and required four tier corrections. These elapsed times are observations from two small suites. [Fresh case traces](evaluation/tier-default-fresh.json).

The billing-plan replay used the same file and labels for both lookup arms. Plain lookup returned plan, kept all three cadence values unresolved, and affected zero rows. The profiled call returned benefit_code after seeing 3/3 supported rows there and 0/3 in plan. The final preview applied the documented professional to pro rule to one row with zero unresolved values. Both made one mapping call. The measured times for this case were 14.273 s and 13.685 s. [Eight-case regression traces](evaluation/tier-default-regression.json).

The normal local browser upload verified membership_band over a billing cadence plan column, two affected rows and one unresolved gold row, and a canonical-only upload. An equal-coverage upload stayed unmapped and a manual selection refreshed its preview. A separate local browser test verified exact approval, edit invalidation and retry-safe import. Backend verification passed 159 tests. The browser runs passed five mock tests and two real Ollama tests.

## Public release verification history

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

Reviewer initial reviews detected 10/13 labeled proposal issues with 10/10 issue precision. All ten were already reported by Python. Across all 17 review calls, precision was 11/11 and recall 11/14. Reviewer added zero incremental detections and missed the one unflagged competing-email issue (incremental precision N/A, recall 0/1). No false mapping alarm appeared on the five correct proposals, but one otherwise valid invalid-tier finding speculated about row numbering without support. All 24 support references resolved; only four were placed in the correct reference bucket. Application normalization handles the misplaced validator IDs. The set showed no final mapping-quality improvement. This is historical Reviewer evidence.

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

The fixed HTTP profile used the historical API workflow. Its artifacts remain available above. Running scripts/profile-local.mjs now measures the active Mapping Agent and category workflow. The historical assessment command still supports both legacy agent variants.

## Limits

The labels are internally authored, synthetic and small. Case ordering, warm caches, model/runtime versions and hardware affect latency. Citation checks are constrained and semantic scoring covers a narrow oracle. Human time savings, production workloads, independent unseen generalization and deployed cloud behavior have not been established. Full raw historical traces/source archives are preserved locally but deliberately excluded from the public repository.
