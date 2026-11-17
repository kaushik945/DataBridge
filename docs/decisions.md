# Engineering decisions

**AI proposes; Python executes.** Unfamiliar source headers and policy aliases benefit from language models, but a typed mapping is easier to inspect and constrain than generated transformation code. Deterministic validation governs the entire file. No agent tool can import records.

**Schema authority is explicit.** Requiredness and allowed values travel as structured schema facts. Optional means absent is permitted, not that every value must be blank. Retrieved policy conflicts are correction requests, not new runtime constraints.

**Ambiguous dates require a person.** Every slash date requires explicit operator format selection. The guard conservatively clears model guesses, even for 13/04/2026. A selected format is strict; ISO does not accept slash dates.

**Approval describes exact state.** File, mapping version/hash and validation hash are bound into approval. Edits/revalidation invalidate it. Imports lock and recheck state, use database uniqueness and persist idempotency outcomes atomically.

**Reviewer is optional.** The measured 16-case comparison found no final mapping-quality gain. Reviewer can surface scoped advisory concerns, but Python decides blockers and whether a repairable deterministic issue warrants the bounded revision. Requests for human date clarification do not trigger automatic guessing/revisions.

**Keep retrieval small and inspectable.** Exact pgvector search is sufficient for the shipped corpus. Model/prefix/dimension identity isolates collections. Changed documents are replaced during ingestion. Citation existence is checked separately from semantic support.

**Measure before optimizing.** Fresh per-call clients/sessions remain because warm setup/parsing cost was under 0.3 ms per call in the measured profile. First-use imports and schema construction were visible. No controlled speedup is claimed. [Results and limits](evaluation.md).
