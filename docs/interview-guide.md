# Technical interview guide

## One-minute explanation

DataBridge onboards customer CSVs using inspectable AI mapping proposals and exact human approval. React sends authenticated uploads to FastAPI. Local Nomic embeddings retrieve policy passages from pgvector; Qwen3 proposes a typed mapping through Google ADK. Python owns schema constraints and full-file validation. An operator resolves ambiguous dates, validates and approves the exact version. A locked transaction imports accepted records, while unique normalized emails and persisted idempotency results protect retries. The default workflow profiles source columns before calling the Mapping Agent and applies documented tier aliases in Python. A historical 16-case comparison found no final quality gain from the generic Reviewer. The verified deployment is local; cloud configuration is prepared and unverified.

## Discuss the boundaries

Why use AI? Both AI variants selected 78/80 source columns versus 74/80 for fixed aliases, but exact mappings were 5/16 versus 14/16. AI recovered unfamiliar headers and still missed required transforms/clarifications. It does not replace validation or operator judgment. Human time saved was not measured.

Why two duplicate controls? Import locks serialize the decision window, database uniqueness catches outside writers and idempotency returns the original committed result on matching retries. A late conflict rolls back the entire import and clears approval.

Why explicit dates? Context cannot safely establish a customer's slash-date order. Human selection is conservative even for individually unambiguous slash values. A selected ISO format rejects slash input. Transform edits invalidate approval.

What did Reviewer add? It reported real issues already found by Python and added latency. Initial precision was 10/10, recall 10/13; the one unflagged competing-email error was missed. Those denominators do not prove general review accuracy. Model concerns remain advisory.

What was debugged? A saved final Investigator and Reviewer both treated optional country as requiring blank. The schema and retrieved passages agreed that country was optional. Missing intermediate traces prevented proving which agent first introduced it. Structured destination facts, validator summaries and scoped findings addressed the payload contract gaps. Two known local reproductions removed the country claim while retaining human date selection. The case is now a development regression, not held-out evidence.

What did profiling show? Warm client setup/parsing were negligible in three fixed-input two-agent runs. First-use imports, schema construction and native model loading contributed to warm-up. No speedup from the earlier 38-second incident is claimed because inputs and warm conditions differed.

## Code to show

Start with [domain.py](../backend/app/domain.py), [review.py](../backend/app/review.py), [agents.py](../backend/app/agents.py), then the approval/import endpoints in [main.py](../backend/app/main.py). Explain retrieval collection identity in [retrieval.py](../backend/app/retrieval.py) and endpoint restrictions in [local_provider.py](../backend/app/local_provider.py). [Evaluation](evaluation.md) links sanitized scores, labels and a real trace excerpt.
