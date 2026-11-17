# Three-minute local demonstration

Complete [setup](setup.md), ingest local knowledge and sign in at http://localhost:5173. Ollama runs separately. Run a suggestion before the timed demonstration to warm the process/model. Reviewer is off by default. For a repeated demonstration, use fresh synthetic email addresses, preserving the sample's duplicate pair.

**0:00-0:30: Upload.** Use [northstar-customers.csv](../samples/northstar-customers.csv). Show the six rows and original headers. Explain that source values and row positions survive transformation.

**0:30-1:10: Inspect.** Suggest mapping, show Qwen3 metadata and open a retrieved policy passage. The model may omit transformations. Confirm the five source columns, YYYY-MM-DD, name trimming and tier aliases starter/basic, professional/pro, business/enterprise. Show that the operator edits the proposal.

**1:10-1:50: Validate.** Save and validate. On an empty destination with the documented mapping, expect three accepted and three rejected rows. Show original/transformed values and the email, calendar-date and duplicate errors. Explain additional destination conflicts honestly if repeating against existing customers.

**1:50-2:25: Approve/import.** Inspect the exact mapping version, valid-only policy and rejected report. Approve and import. Show the receipt/history and report download. Mapping/date edits invalidate approval; identical import retries reuse the persisted result.

**2:25-3:00: State limits.** Show [evaluation](evaluation.md): 78/80 AI source choices but only 5/16 exact mappings, versus 14/16 baseline. Reviewer did not improve final quality. The separate fixed-input two-agent profile had an 8.086-second median across three warm repetitions. These are synthetic development results and local hardware observations.

Afterward, use [ambiguous-dates.csv](../samples/ambiguous-dates.csv) to demonstrate explicit slash-date selection. Choosing YYYY-MM-DD must reject 03/04/2026. Prepared cloud files are not a verified deployment.
