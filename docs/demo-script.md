# Three-minute local demonstration

Complete [setup](setup.md), ingest local knowledge and sign in at http://localhost:5173. Ollama runs separately. Run a suggestion before the timed demonstration to warm the process and model. For repeat demonstrations, use fresh synthetic email addresses.

**0:00-0:30: Upload.** Use [category-preview.csv](../samples/category-preview.csv). The four rows include a misleading plan column containing billing cadence and a membership_band column containing tiers.

**0:30-1:10: Inspect.** Suggest mapping and open Tier source coverage. Show 0/4 supported values for plan and 3/4 for membership_band. Open the alias policy for professional to pro and show the two affected rows. Check the sources, leave country unmapped, and select DD/MM/YYYY for this example.

**1:10-1:50: Validate.** Save and validate. Expect three accepted rows and one rejection on an empty destination. Show how the preview and rejection report handle the unsupported gold value.

**1:50-2:25: Approve and import.** Review the exact mapping version, valid-rows-only policy and rejected report. Approve and import, then show the receipt. Mapping or date edits invalidate approval. Matching import retries return the persisted result.

**2:25-3:00: Explain the results.** In the original eight-case replay, correct tier decisions improved from 3/8 to 8/8. On five fresh synthetic cases, they improved from 1/5 to 5/5. Both lookup workflows made one model call per file. Weak or tied evidence still requires the operator to select a source. See the [evaluation and per-case traces](evaluation.md#promoting-upfront-profiles).

Afterward, use [ambiguous-dates.csv](../samples/ambiguous-dates.csv) to demonstrate explicit slash-date selection. Choosing YYYY-MM-DD rejects 03/04/2026.
