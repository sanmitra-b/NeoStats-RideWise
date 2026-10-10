# RideWise: Design Decisions and Next Steps

RideWise is a read-only rental-support assistant: customers can ask about their own bookings and policies, while
support staff can inspect permitted operational data and dashboards. Answers include SQL, PDF pages, or calculation evidence so they can be checked.

## 1. Three most important design decisions

### 1. Keep the source data immutable and make the assistant read-only

The supplied SQLite database is opened in immutable, query-only mode. The
assistant can explain a cancellation, refund, payment, late-return, damage, or
EV rule, but it cannot cancel a booking, issue a refund, change a vehicle, or
write back to the source records. Derived projections, conversation history,
embeddings, OCR output, and indexes live separately under `derived/`.

This was the most important safety and scope decision. The challenge supplied a
static snapshot, not a transactional system, and the three-hour build window
did not justify implementing mutation workflows or payment integrations.
Keeping the source untouched also makes the demo reproducible and prevents an
incorrect model answer from becoming an irreversible data change.

### 2. Use bounded, typed operations instead of allowing the model to write SQL

Routing is hybrid. Deterministic rules handle common booking lookups, policy
questions, refusals, and supported calculations; the configured NeoStats model
handles interpretation and structured planning where wording is less
predictable. The model can select only a known operation and typed filters.
The backend owns SQL templates, columns, joins, aggregates, ownership
restrictions, row limits, and parameter binding.

This provides useful natural-language coverage without turning the model into a
database administrator. It prevents arbitrary tables and joins, reduces
prompt-injection risk, and makes financial calculations deterministic with
`Decimal`. Payment rows are reduced to booking grain before analytics joins so
multiple payments do not inflate booking counts. The trade-off is that an
unsupported question must be clarified or refused rather than answered
creatively.

### 3. Separate identity/PII access from operational chat and require evidence

Firebase verifies identity and trusted role claims. A private server-side
mapping links a Firebase UID to a supplied customer ID; signing up does not
automatically grant access to an existing customer record. Customer chat uses
an operational projection that excludes the customers table and selected
free-text/private fields. Profile and support-directory paths have separate
authorization and return only the minimum masked fields needed.

Policy content is indexed in local Qdrant with local BGE embeddings and OCR for
image-heavy pages, while customer records and conversation history are never
embedded. Every substantive answer carries executed SQL and/or source PDF
pages; calculations expose inputs and formulas. This decision makes answers
auditable and limits the blast radius of a model error or an overly broad
query. It also acknowledges that this is separation inside one backend
process, not a complete production PII service.

## 2. Alternatives considered and rejected

* **Writable bookings and payment actions:** rejected because the supplied data
  is a snapshot and the demo does not have a safe payment or transaction
  boundary. We kept explanatory workflows instead.
* **Free-form model-generated SQL:** rejected because it would weaken
  authorization, make joins and financial totals difficult to review, and
  create an unnecessary injection surface. Typed operations and application-
  owned SQL are more predictable.
* **A fully autonomous multi-agent system:** rejected for this scope. The
  visible Router, Booking/Payments, Analytics, Profile, Policy/EV, Charges,
  Answer, and Verification stages are controlled workers, not independent
  agents negotiating hidden plans. This gives clearer progress and fewer
  model calls.
* **PostgreSQL, Docker, hosted vector search, or multiple backend services:**
  rejected for the local hackathon snapshot. SQLite, persistent local Qdrant,
  and one FastAPI process reduce setup and credential risk. The consequence is
  weaker portability and no multi-process deployment story yet.
* **Keyword-only policy search:** rejected because policy questions require
  semantic paraphrase handling and scanned visual content. Local embeddings
  plus OCR preserve that capability without putting customer data into the
  vector index.
* **A frontend framework and a separate frontend build:** rejected because
  vanilla HTML/CSS/JavaScript was sufficient for the chat, evidence drawer,
  dashboards, charts, and filters within the time limit. The cost is more
  manual state management and accessibility work.

## 3. Where the assistant currently fails or behaves poorly

The assistant is reliable only within the implemented operation catalogue and
the supplied snapshot. Unusual wording can defeat keyword routing, and an
ambiguous request may need a clarification instead of producing a useful
answer. The model and provider are also external dependencies: timeouts,
invalid structured output, or provider unavailability are reported explicitly,
but there is no alternate generative provider. Database facts and deterministic
calculations can still work during a provider failure.

Policy retrieval has useful selected paraphrase tests but no formal recall
benchmark, reranker, minimum similarity threshold, or sparse/dense hybrid
search. A weakly related question can therefore retrieve the nearest passage
and produce a verbose or insufficiently relevant evidence set. The
220-word, 40-word-overlap splitter is judgment-based and does not understand
sentences, headings, tables, or embedding-token limits. OCR can misread small
text, symbols, or table relationships.

Evidence validation confirms that cited IDs and critical values exist; it does
not prove that every cited row entails the generated conclusion. A model can
cite a real page and still overinterpret it. The interface has not had a full
accessibility or browser-compatibility audit. History is local to one backend,
sessions are not durable across restarts, and there is no retention schedule,
per-user quota, complete audit trail, or multi-process vector service.

The application also cannot verify facts absent from the snapshot, such as a
real payment-gateway deposit return, holiday-aware refund timing, or live
changes made after the snapshot. City aliases such as Bangalore, Bengaluru,
and BLR are normalized for reporting, but this is an interpretation for
comparison and does not alter the source records.

## 4. What I would build next with one more week

First, I would create a reviewed evaluation set of representative booking,
policy, OCR, authorization, and analytics questions. Each case would specify
the expected operation, rows/pages, calculation, and refusal behavior. I would
measure retrieval recall, citation correctness, numeric correctness, latency,
and authorization failures before changing chunking or prompts.

Second, I would improve retrieval with section- and table-aware, token-aware
chunks, a reranker or minimum relevance threshold, and more precise
cell/paragraph citations. I would expand the typed operation catalogue only
when the evaluation set shows a real coverage gap, keeping unsupported
requests explicit rather than hiding uncertainty.

Third, I would harden deployment and privacy: durable server-side sessions,
token/revocation handling for active streams, per-user quotas, structured
audit logs, retention and encryption controls, and a narrower PII service.
Finally, I would run a real browser accessibility/authentication pass and add
contract tests for the provider, Firebase, OCR/index readiness, and
multi-process deployment. These improvements would make the assistant safer
and measurable before making it more autonomous.
