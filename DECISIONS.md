# RideWise: engineering decisions and assumptions

Updated 10 October 2026. This describes the implementation we have today, rather than the original wish list. Where a setting was chosen by engineering judgment, I say so. A passing test is evidence for the cases it covers; it is not proof that every possible question or deployment is correct.

## 1. What we are trying to deliver

RideWise is a read-only assistant for customers and support staff. It combines supplied booking records with the supplied policy PDFs, explains the result, and shows where that result came from. The interface also provides a policy library, customer booking cards and support dashboards.

The three-hour hackathon influenced nearly every infrastructure choice. We prioritized a working local application, reliable authorization, correct money calculations and visible evidence. We avoided adding services simply to make the architecture look larger. The user's requests shaped the scope: FastAPI with HTML/CSS/JavaScript, Firebase authentication, separated customer PII, semantic RAG with a vector database, visible routing and the requested dashboards. SKOPE informed the workspace arrangement; NeoStats informed the black, green and white visual direction. The implementation was written for this project rather than copied from SKOPE.

The supplied documents are requirements and source material. Text inside a PDF does not authorize the application to execute an instruction, contact someone or change a record. Similarly, a retrieved passage is evidence for an answer, not a command to the assistant.

## 2. The application stack

We chose FastAPI because the server needs authenticated API routes, validated inputs, Python calculations and streamed progress. Using one Python application also lets it share the environment with PDF processing and local embeddings. Pydantic models define the allowed request and planning structures. Unknown fields and invalid operation names are rejected rather than interpreted loosely.

The frontend is ordinary HTML, CSS and JavaScript. That keeps setup small and avoids a separate frontend toolchain. It is sufficient for chat, evidence panels, filters, cards and charts. The cost is that routing, component state and accessible interactions require more manual work than they would with a mature frontend framework.

We did not introduce Docker. For this local demo, configuring containers, mounts and credentials would consume time without solving an immediate deployment problem. Ecothon is the runtime environment, and requirements.txt records the Python dependencies. This is less portable than a tested container image. A production deployment would need reproducible installation and deployment checks beyond the current laptop setup.

## 3. The source database stays immutable

The application opens ridewise.db in SQLite read-only, immutable mode, enables query_only and disables extension loading. It never performs a cancellation, refund, payment, vehicle update or damage-status change. It can explain what an action would mean under the implemented rules.

The immutable setting assumes the supplied file is a static snapshot. It is appropriate for the hackathon; it would be the wrong setting for a live database being updated by another process. Supporting data goes into ignored derived files, not the supplied database. Source hashes are checked against a baseline so that accidental changes can be detected.

We kept SQLite because it is already the supplied format and the dataset is small. Moving it into PostgreSQL would add migration work and another service. There is no need for that to answer questions over this snapshot.

## 4. Identity, roles and customer ownership

Firebase handles email/password and Google sign-in. A normal newly registered account receives the customer role through the backend bootstrap flow. The browser cannot assign itself a support role or choose its own customer mapping. Existing trusted claims are preserved when the account is bootstrapped.

The backend verifies Firebase ID tokens, including revocation checks. A 30-second allowance accommodates modest laptop clock drift; it does not remove signature, audience or expiry checks. We removed the earlier custom sign-in token interface. Normal Firebase tokens still have their normal lifecycle. A fixed evaluator password does not mean a permanent bearer token.

Support access is assigned through trusted Firebase Admin code, such as scripts/provision_identity.py. Firebase Authentication's account list is not a substitute for application role assignment: this app reads custom claims. After claims change, the client needs a refreshed token. Credentials and customer mappings are kept out of Git.

Identity and data ownership are separate. Firebase UID identifies the signed-in person. A private server-side mapping links that UID to a supplied CUST identifier. Signing up does not create a row in the supplied database or prove ownership of an existing customer record. Until an administrator links the account, the user can read policies but cannot retrieve personal bookings.

An evaluator may deliberately start a customer or support session for demonstration. The effective session role still matters. An evaluator operating in customer mode cannot call the support dashboards. Ordinary customer or support accounts cannot use this evaluator privilege.

Session IDs are bound to the authenticated UID and current assigned access. Hiding a tab is only a UI convenience; server dependencies reject unauthorized calls before dashboard queries execute. Role changes during an already running request are not instantaneously propagated through every step. Production would need a stronger policy for revocation, ongoing streams and auditing.

## 5. How PII is separated

General chat queries run against a temporary in-memory operational projection. The customers table is not available there. A small customer_attributes table supplies customer ID, tier, KYC status and canonical residence city for permitted filters and calculations. The other projected tables exclude selected free-text and transaction-reference fields.

Customer sessions receive only their operational records and related vehicles. This limits the data available to the tool itself rather than relying on a model to remember an ownership rule. Authorization is also checked before planning and query execution.

The private profile path can access customers, but it checks the requested identity separately. Customer-directory dashboards select only the necessary columns and mask names before returning rows and evidence. They exclude phone, email, date of birth and licence number. Support contact lookups require one explicit customer and mask contact details. Profile answers do not send private contact fields to the generative model.

This is separation inside one backend process, not a separate security service. The process still has permission to read the source customer table. City, tier and KYC are also personal attributes, even though they are less identifying than contact details. We expose them only in the relevant authorized workflow. A production version should isolate PII behind a narrower service and add retention, encryption and audit controls.

## 6. Bangalore, Bengaluru and BLR

The supplied customer table uses Bengaluru, Bangalore, BLR and a lowercase Bangalore spelling with trailing whitespace. Together they represent 164 of the 200 customers in this snapshot. Treating them separately made the city chart and filter counts misleading.

We use Bengaluru as the canonical display and comparison value. An explicit alias list handles casing and surrounding whitespace. Dashboard SQL uses a CASE expression so filtering, chart grouping, options and returned city values agree. The operational projection also supplies canonical city values, and typed city filters normalize their input. Model planning receives a normalized question while saved user messages retain the original wording.

This is an interpretation of equivalent labels, not a correction written back to source records. The executed SQL evidence shows the transformation. Other city names are not fuzzy-matched. For example, Mangaluru remains distinct and Bangalore Rural is not silently merged into Bengaluru.

In chat analytics, city means the customer's residence city. It does not mean the booking's pickup location. Hub names such as Koramangala and Whitefield are neighborhoods and remain separate identifiers. Vehicle-only tools do not infer city from a customer's residence. City normalization does not broaden a customer's access to anybody else's data.

## 7. Routing and the meaning of agents

Routing is hybrid. Explicit booking lookups, recognizable policy questions, simple booking lists and certain refusals use deterministic rules. Other questions go to the supplied model for a structured Plan. The model chooses an operation from a bounded catalogue and typed filters. Customer counts use a separate support-only customer_analytics operation, grouped by tier, KYC status or canonical residence city. They count customer rows rather than bookings, so customers with no bookings are included and repeat bookings do not inflate counts. Recognizable customer-count requests route to it before profile keywords such as tier. Profile lookup still requires one explicit customer for support staff; aggregated counts do not expose contact records. It never returns SQL for direct execution.

The visible Router, Booking/Payments, Analytics, Profile, Policy/EV Guide, Charges, Answer and Verification stages are workers in a controlled workflow. They are not independent autonomous model instances negotiating a solution. Progress events report actual selected work and evidence IDs; they do not reveal hidden reasoning.

This arrangement saves model calls for interpretation and explanation. It also lets explicit lookups and implemented calculations work when the provider is unavailable. The tradeoff is coverage: the catalogue cannot express every conceivable question. Unsupported or ambiguous requests should ask for clarification rather than invent a new query. Keyword routing can also misclassify unusual wording, so its behavior deserves continued testing.

## 8. SQL is compiled from validated operations

The application owns the SQL templates, allowable columns, operators and aggregate expressions. User values are bound as parameters. Contains filters escape wildcard characters. Request models cap filter counts and input lengths. The model cannot choose a table outside the catalogue, add an arbitrary JOIN or remove an ownership restriction.

General chat queries display up to 50 rows. Dashboard tables use 100-row pages; selected detail and fleet queries have larger bounded caps. The query runner fetches one extra row to flag truncation and interrupts work that exceeds roughly two seconds. These are practical demo limits, not benchmark-derived capacity guarantees. A truncated transaction set is not used to calculate a partial financial total.

Payment aggregates are reduced to booking grain before they are joined into booking analytics. Dashboard payment filters use EXISTS when selecting bookings. Otherwise, a booking with several payments or damage reports could be counted several times. This is a data-model issue that prompting alone cannot fix.

## 9. What enters the RAG index

Only the supplied policy content enters Qdrant. Customer records, profiles and conversation history are not embedded. SQLite answers operational questions; policy retrieval answers questions about the documents. This keeps the retrieval corpus small and avoids placing customer PII into a second searchable store.

Selectable text is extracted with pypdf. PDF filenames, versions, page numbers, source hashes and extraction methods are retained. The original PDFs remain available through authenticated links so users can inspect the source rather than trust a generated summary.

## 10. Chunking: 220 words, 40-word overlap

The splitter uses whitespace-delimited words, not model tokens. Each passage contains at most 220 words. Successive passages start 180 words apart, giving 40 words of overlap. Chunks stay within a single PDF page and within an extraction segment. Short pages produce shorter chunks; we do not pad them.

We wanted enough context to retain a policy clause and its conditions without embedding a whole long page containing unrelated topics. Overlap helps when a condition and consequence fall on opposite sides of a boundary. These settings were chosen by judgment for a small policy pack. They have not been established as optimal through a comparison of chunk sizes.

Page boundaries make citations precise but can separate a rule continued on another page. The splitter also does not understand headings, sentences or table structure. It does not explicitly check the embedding tokenizer's length limit. Section-aware, table-aware and token-aware splitting are sensible improvements, especially for a larger or more complex corpus.

Native text plus hash-reviewed visual transcriptions form one segment. OCR forms an additional segment. We initially mixed all of that together; a retrieval test then ranked a late-return paraphrase less well. Keeping the existing passages intact and adding independent OCR passages fixed that observed regression. Some duplicate text remains because full-page OCR also reads selectable text. We accepted this for the small corpus rather than risk removing unique image text with an aggressive deduplication rule.

The current index has 28 passages from 11 pages. That count is a property of this document pack and implementation, not a configured limit.

## 11. Embeddings and vector retrieval

Local embeddings use BAAI/bge-small-en-v1.5 through FastEmbed, with 384-dimensional vectors and ONNX CPU execution. We use two threads and document batches of 16 as modest laptop settings. Documents use passage embedding and questions use query embedding. No GPU is required for this setup.

The supplied briefing permits a local open-source embedding model when no event embedding model is supplied. Generative planning and explanation still use the NeoStats-provided endpoint. If an event embedding model is configured, the app uses that supplied endpoint and does not silently switch providers on failure.

Qdrant runs in persistent local mode. We chose it to provide genuine semantic retrieval and metadata filtering without another server, account or hosted service. Cosine similarity ranks the top eight chunks after policy-topic filtering. Eight was selected to provide supporting conditions and nearby clauses; it was not tuned against a large evaluation set.

Retrieved chunks are grouped into page evidence, and related reviewed visual annexures are added when necessary. Therefore, eight retrieved chunks does not mean eight distinct pages or an absolute limit of eight evidence items. Scores are shown as retrieval similarity, not answer-confidence percentages.

There is currently no reranker, minimum similarity threshold, sparse/dense hybrid retrieval or formal recall benchmark. A weakly related question can still retrieve the nearest passages. Policy-only answers can consequently be verbose. The paraphrase tests demonstrate useful behavior on selected questions, not universal retrieval accuracy.

## 12. OCR for PDFs 3, 4 and 5

We render every page in those three documents at 240 DPI with PyMuPDF and process it locally with RapidOCR on ONNX CPU. That includes mixed pages with both selectable paragraphs and image-only figures. Merely checking whether a page has extractable text would miss the images on those pages.

240 DPI is a practical balance between small-text readability and processing cost. We have not benchmarked several resolutions. OCR boxes are ordered by location, and nearby boxes are grouped into rows to help retain table cell associations. This is a simple layout heuristic, not a complete table parser. It can still separate a percentage from its condition or misread a symbol.

Evidence records OCR status, recognized line count, engine, DPI and mean recognition confidence. Complete means the engine returned text; it does not prove every region was recognized correctly. Empty and failed pages are retried rather than cached as success. The explicit index-build command refuses incomplete OCR coverage, and health reports ocr_ready independently of semantic_ready. Runtime semantic preparation can still index available text if OCR fails, so readiness fields must be checked together before a demo.

OCR reads text; it does not reliably infer the meaning of unlabeled arrows, colors or shapes. Reviewed figure transcriptions remain useful for that reason. Financial rules continue to follow the reviewed transcriptions rather than unreviewed OCR numbers. Native selectable text takes precedence over conflicting OCR. The explanation prompt makes this priority explicit, but prompting is not a proof of compliance.

## 13. Caches and source integrity

Successful OCR results are cached by source SHA-256, page number, rendering DPI, OCR version and renderer version. Changing those inputs produces a new cache key. Cache files are written through a temporary file and then replaced. A failed extraction does not permanently poison the cache.

The vector collection fingerprint includes the embedding model/provider, passage content and source hashes. A complete matching collection is reused; a changed corpus builds a different collection. Model files are also cached locally. This removes repeated OCR and document embedding work from normal startup.

Derived OCR, vectors, models and history are excluded from Git. They can contain source content or personal conversations and should remain private. Old fingerprinted vector collections are not automatically garbage-collected. A production version needs cache lifecycle and storage policies.

Hash-reviewed policy rules are bound to the original PDF hashes. If a required policy changes, the implemented financial calculation is disabled pending review. A hash detects a change; it does not establish that a document is correct or legally authoritative. Human review is still necessary when replacing a policy.

## 14. Financial calculations and business assumptions

Money is calculated in Python using Decimal and rounded to two places with ROUND_HALF_UP. The model is not trusted to perform arithmetic. Rule constants live in rule_catalogue.json and are linked to reviewed policy evidence; they are not canned answers tied to particular bookings.

Refund version selection uses booking creation time. The v2 cutoff is 1 July 2026 at midnight IST, represented as 30 June 2026 at 18:30 UTC. A later cancellation does not move an older booking into v2. Customer cancellation bands use the recorded lead time; RideWise cancellation and no-show statuses have explicit overrides. A cancellation after pickup is rejected by this advance-cancellation calculation. An uncancelled booking does not acquire an actual refund entitlement merely because someone asks about one.

Refund entitlement uses successful BOOKING amounts and proportional recorded GST. Failed and pending payments are excluded. Recorded REFUND amounts are negative in the supplied schema and are converted to a positive comparison amount. A reconciliation difference is a flag, not proof that the payment gateway failed to transfer money. Deposit returns occur outside the supplied transaction evidence and cannot be verified here.

Late fees use the full lateness, rounded up to begun hours, at 1.5 times the hourly rate. Gold's 30-minute grace is inclusive. Once it is exceeded, the grace is not deducted from lateness. Standard and Silver have no grace under the reviewed annexure. Actual late/battery charges are established only for completed bookings. The low-battery fee applies to EV returns below 10%; exactly 10% is not below the threshold. Missing or invalid battery readings remain uncertain rather than being replaced with a guessed value.

Only CHARGED damage reports enter the calculated charge amount. OPEN and DISPUTED reports are surfaced as unresolved; WAIVED reports do not become charges. GST is calculated separately. Assessed charges and successful penalty payments are compared, never added together as if they were separate debts.

Rental estimates use scheduled duration, full 24-hour blocks and remaining hourly charges capped at the daily rate. The current calculator requires a positive whole number of hours and the two-hour minimum. It does not invent rounding rules for fractional-hour inputs. Deposits are shown separately without GST under the implemented rental rule. A scheduled estimate is not a recorded payment.

## 15. Analytics definitions and timestamps

In chat analytics, revenue means successful BOOKING base amounts excluding GST, deposits, refunds and penalties. Refund and penalty metrics use their explicitly defined successful transaction totals. Utilization currently means completed rental hours, not a percentage: the dataset and tool do not supply a capacity/time denominator. Chat monthly grouping uses the stored UTC scheduled-start month; it is not yet an IST business-month calculation.

Dashboard money totals are separated by payment type and status, with base and GST in separate columns. Negative refunds remain negative in transaction displays. Damage summaries show assessed cost rather than claiming the money was collected.

Stored timestamps are interpreted as UTC. Booking cards and dashboard timestamp displays use Asia/Kolkata. Dashboard date filters refer to scheduled pickup and cover the selected IST calendar days, translated to UTC with an exclusive next-day end bound. Date-only commissioning fields remain dates. Raw SQL evidence and deterministic fallback record answers can retain UTC and label it as such; display formatting is not a change to storage.

An ONG status marks an ongoing booking for vehicle indicators. We rely on the supplied snapshot status rather than recomputing state from the current wall clock. Late-return flags compare actual return to scheduled end; they do not by themselves determine whether grace eliminates a fee. Past booking cards include completed and no-show records; cancellation cards include customer and system cancellations.

## 16. Evidence and generated answers

Every substantive data or policy answer carries executed SQL and/or used PDF pages. Calculations additionally expose inputs, formulas and rule sources. Refusals and clarification questions can have no evidence because no substantive retrieval was performed.

The generative answer must return structured claims with evidence IDs. We verify that cited IDs exist and that critical numeric values and identifiers appear in cited evidence. Invalid explanations fall back to records or original excerpts. Financial and private-profile answers use deterministic output directly.

This validation checks provenance, not full meaning. A number might exist in the evidence but belong to another row. A model can cite a real source while drawing an unsupported conclusion. Independent claim-entailment tests and more precise cell-level citations would strengthen this substantially.

Retrieved text and user messages are treated as untrusted input in the explanation prompt. Server-side scopes, fixed tools and deterministic calculations provide stronger boundaries than that prompt alone.

## 17. Model calls, responsiveness and failures

Planning and explanation use only the configured NeoStats generative provider. Temperature is zero, responses are capped at 1,800 output tokens and parsed against strict schemas. These settings encourage predictable structured output; they do not make model responses perfectly deterministic.

The default timeout is 25 seconds, configurable within a 5-to-45-second range. At most three model calls run concurrently. Automatic retries are disabled to avoid hidden delays and extra rate-limit consumption during the demo. Invalid JSON, provider errors and timeouts are reported explicitly. There is no silent alternate generative provider.

OCR and embedding inference use CPU settings with limited threads. Blocking work runs outside the async request loop. Local Qdrant access is serialized, and this deployment supports one backend process. Multiple Uvicorn workers or a concurrent standalone index builder are not supported against the same local store. The app should be stopped before running the index-build command.

Database facts and implemented calculations can remain available during provider failure. Policy semantic retrieval reports unavailable if the embedding/index operation fails; it does not secretly substitute keyword search. A generated explanation failure may still yield source excerpts, which is a different and explicitly described fallback.

## 18. Conversation history and session state

Saved conversations live in a separate private SQLite file under derived, not Firestore and not ridewise.db. We chose this because there is one local backend and no requirement for synchronizing history across installations. Firebase establishes identity; it need not store all application data.

History includes questions, results/evidence and worker events, so it can contain personal booking information. Reads and deletes are scoped to UID and current access. An evaluator can inspect their own saved conversations across their demonstration roles; evaluator status does not grant access to another UID's history. Signing out clears visible browser content but does not delete saved server history. Users can delete their saved conversations.

History survives server restarts on this computer. Active sessions do not. Sessions expire after an hour of inactivity, and creating another session for the same UID invalidates the old one. The session store has a 200-session cap. Conversation context retains a recent bounded question list and a booking reference, rather than sending the complete saved history to every planning call.

Generation counters prevent an old streamed response from being attached to a reset conversation. Request identifiers help avoid duplicate turns. These mechanisms address common reset/retry races; they do not replace a durable distributed job system. There is no automatic cross-device history synchronization, encryption-at-rest feature or retention schedule yet.

## 19. Interface choices

The workspace separates chat, evidence, routing progress and saved conversations so that the answer and its proof can be inspected together. Dedicated policy, booking and dashboard pages prevent those workflows from overcrowding chat. Role checks determine navigation visibility, with independent authorization on the server.

The policy library opens the unchanged PDFs through authenticated requests. Customer booking cards prioritize status, vehicle, hub and IST times, then reveal payments, refunds and claims on expansion. Support dashboards use filters and full filtered summaries with paginated rows. Selecting a customer opens that customer's bookings. These screens are fixed database views; they do not need an LLM call to render.

Charts use canvas and tables provide the underlying values. User and source text is inserted through textContent rather than interpreted as HTML. Independent scroll areas keep long chats and evidence usable. Styling and basic rendering have been checked, but this is not a completed accessibility or browser-compatibility audit.

## 20. Verification, remaining gaps and the next sensible work

The regression suite covers selected authorization/ownership cases, financial boundaries, structured-query behavior, dashboard aggregation, semantic paraphrases, OCR caching/failure and city normalization. Automated tests disable live generative calls, use isolated history/vector stores and do not consume the event model budget. Separate checks verify source hashes, dependency consistency and JavaScript syntax.

Local readiness checks confirm configuration and successful preparation; they are not a substitute for a live evaluator sign-in and a real provider request. Firebase/provider connectivity depends on external configuration. One earlier in-app-browser login attempt encountered a network error even though backend checks worked. We should not treat that as a completed end-to-end browser authentication test.

The largest remaining quality gaps are retrieval evaluation across more questions, section/table-aware chunks, stronger generated-claim validation and broader analytics coverage. The largest deployment gaps are durable sessions, per-user quotas, stricter audit/retention controls, PII service isolation and a multi-process vector service. Holiday-aware refund timelines and real payment-gateway settlement data are absent, so we do not claim to verify them.

With more time, I would first add a small reviewed question-and-evidence evaluation set and measure chunking/retrieval alternatives. Then I would improve the typed query catalogue and table citations. For an actual deployment, privacy, revocation and operational controls would take priority over making the agent workflow more autonomous.

## 21. Where the implementation lives

| File | Responsibility |
|---|---|
| app/main.py | HTTP routes, lifecycle, endpoint authorization and streaming |
| app/auth.py | Firebase verification, trusted roles and customer bootstrap |
| app/sessions.py | Effective role, ownership, inactivity and reset state |
| app/models.py | Validated requests, tool plans and generated claims |
| app/assistant.py | Hybrid routing, worker sequence, scope checks and answer verification |
| app/provider.py | Supplied model calls, prompts, schemas and failure handling |
| app/database.py | Read-only source access, scoped projection, private profiles and compiled SQL |
| app/dashboards.py | Fixed dashboard/booking queries, summaries and date filters |
| app/locations.py | Explicit city aliases and canonical SQL expressions |
| app/calculations.py and app/rule_catalogue.json | Decimal calculations and reviewed policy constants |
| app/policies.py | PDF extraction, reviewed annexures, citations and policy integrity |
| app/ocr.py | Rendered-page OCR, reading order, status and cache |
| app/semantic.py | Chunking, embeddings, Qdrant collections and retrieval |
| app/history.py | UID-scoped persistent conversation storage |
| app/config.py | Environment configuration and derived-store paths |
| static/app.js | Authentication, chat, history, streaming and evidence UI |
| static/pages.js | Policy library, customer cards and support dashboards |
| scripts/build_policy_index.py | Pre-demo OCR/index preparation |
| scripts/provision_identity.py | Trusted role and customer-link administration |
| scripts/check_sources.py | Original-source integrity verification |
| tests/ | Executable checks of the selected assumptions and behaviors |

This document records the present implementation. IMPLEMENTATION_PLAN.md and UI_SPECIFICATION.md explain the intended direction, but older proposals should not be mistaken for features already built.
