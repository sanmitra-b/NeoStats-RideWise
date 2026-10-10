# RideWise Assist UI specification

Design only; no application UI has been implemented. Companion to `IMPLEMENTATION_PLAN.md`.

## 1. Design direction

Keep SKOPE's workspace pattern: persistent left navigation, central conversational workspace, contextual evidence drawer on the right. Recreate this layout with fresh event-time HTML/CSS/JS; do not reuse pre-event SKOPE component code.

Borrow NeoStats' bold sans-serif headings, rounded white surfaces, restrained spacing, and green calls to action. The reference site's inspected button green is `#5CB52E`, with Geist/system sans-serif typography and approximately 12px button radii. The RideWise palette below adapts these visual cues to the user's black/green/white theme; it is not a claim that all tokens are official brand colours.

| Token | Value | Use |
|---|---|---|
| Ink | `#101410` | Sidebar, header, primary text |
| Green | `#5CB52E` | Primary controls, selected worker, restrained accents |
| Deep green | `#245C18` | Small text on white, source links, success labels |
| Paper | `#FFFFFF` | Chat/evidence reading surfaces |
| Canvas | `#F4F6F2` | Main background |
| Soft green | `#EAF5E3` | Selected tab, evidence/worker status backgrounds |
| Border | `#DCE2D8` | Dividers, cards, input outlines |
| Secondary text | `#556052` | Metadata and explanatory labels |

Use near-black text on bright green buttons; white on this bright green is not the default for small text. Check contrast before delivery. Use a system sans-serif stack (Geist only if already available); no external font/image dependency is required. Body 15-16px, labels 12-13px, chat heading 28-32px; restrained 8/12/16/24px spacing; cards/buttons about 12px radius.

## 2. Desktop workspace

At roughly 1440px width, use a 224px dark sidebar, flexible central chat, and a 360-400px evidence panel. The right panel opens on an evidence badge; show a useful empty-state prompt when no source is selected. At smaller widths it becomes a dismissible drawer rather than crushing the chat.

```text
┌─────────────────┬────────────────────────────────┬───────────────────────┐
│ RIDEWISE ASSIST  │ Conversation     role/customer │ Evidence     Close    │
│                 │ Firebase verified   New chat   │ SQL | PDF | Formula   │
│ + New chat      ├────────────────────────────────┤                       │
│ Conversation    │ User message                   │ Executed statement    │
│ Policy sources  │                                │ Scoped parameters     │
│ Session         │ Routing: SQL + Policy → Charges│ Result rows / limits  │
│                 │         → Answer → Verify      │                       │
│                 │ Answer                         │ PDF name/page/version │
│                 │ [Executed SQL] [PDF sources]   │ Exact source excerpt  │
│                 │ [Calculation]                  │                       │
│ Current role    │ Follow-up options              │ Formula and inputs    │
│ Customer ID     ├────────────────────────────────┤                       │
│ Sign out        │ Message field             Send │                       │
└─────────────────┴────────────────────────────────┴───────────────────────┘
```

The separate SVG wireframe illustrates layout and styling only. Its labels are placeholders, not database results or fabricated answer evidence.

### Sidebar

RideWise wordmark, one prominent green New Conversation control, Conversation, Policy Sources, and Session. These items open actual sections/drawers; no empty Reports/Admin navigation. Footer shows effective role and customer scope where applicable, plus sign-out. Do not display customer names/contacts globally just to personalise the shell.

### Header and empty state

Header separates the verified principal from the effective evaluation role: **Firebase verified** and **Evaluating as Customer / selected ID**, or Support Agent. Avoid implying that a dropdown authenticates someone. Keep New Conversation and allowed Switch Session available without scrolling.

Empty state: short welcome and question categories such as booking details, payments, refund rules, and EV guidance. Agent-only analytics suggestions stay hidden for a customer. Suggestions submit normal requests; none has a stored answer.

### Messages and composer

Compact user card, larger white assistant card, readable line lengths, and visible evidence badges. Preserve message/evidence association. Composer is pinned within the chat column; Enter sends, Shift+Enter adds a line. Disable duplicate submission while the same turn is active, show Stop, and preserve the input on retryable failure. New Conversation cancels the browser stream and invalidates pending server responses.

## 3. Firebase and session screens

Two stages: **verify identity**, then **start permitted session**. For an evaluator, a provisioned Firebase custom sign-in token can be exchanged through the Firebase SDK; retain only in-memory authentication state and clear the token-entry field immediately. Never embed an evaluator token in a URL or source file. A regular account uses its preassigned role/customer mapping.

The verified evaluator sees Customer + customer ID, Support Agent, and Start Session. Customer ID is required/validated only for Customer. Regular users cannot choose elevated roles or another customer. Show a separate evaluator-mode label so testing privileges are transparent. Switch Session is available only where permitted; it clears old history/evidence. Sign-out clears both identity and session state.

If Firebase is not configured, display **Authentication setup required** and the next setup action. If verification fails, block protected requests. Do not silently show a verified badge or fall back to a public staff selector. Any explicitly configured localhost evaluation-only mode has its own clear label and must never masquerade as Firebase authentication.

## 4. Visible multi-agent routing

Each assistant turn contains a collapsible **Routing & execution** strip. Show the selected workers and their actual status. A mixed refund request could route Booking/Payments + Policy, then Charges, Answer, and Verification. A policy-only request must not pretend to run SQL.

Available workers: Profile (protected PII), Booking/Payments, Analytics, Policy, Charges, EV Guide, Answer, and Verification. They are bounded modules/tools sharing authorised evidence; the UI must not claim each is an independent generative model.

Status mapping:

- Queued: outline node + label.
- Running: green outline and progress indicator.
- Completed: deep-green check + elapsed duration.
- Skipped: muted node + reason where useful.
- Failed: clear error label/icon, not colour alone.

Live events come from the backend, keyed by request and session generation: routing, worker start/completion/failure, and final result. Expand to see safe summaries such as **Retrieved permitted booking/payment facts** or **Selected policy by booking creation time**, plus evidence IDs. Do not show private model reasoning, prompts, tokens, raw PII, or unverified answer fragments. If the stream drops, label the interruption rather than animating fictional progress.

## 5. Every substantive answer has source evidence

| Answer type | Mandatory source presentation |
|---|---|
| Database/profile/analytics | Executed SQL badge, exact executed statement, scoped/masked parameters, permitted results |
| Policy/EV guidance | PDF badge, filename, page/section/figure, version, relevant excerpt |
| Database + policy/calculation | Both badge types plus calculation trace tied to input/rule evidence |
| Clarification/access denial/provider error | Control-response label and truthful evidence state; never fabricate a query or PDF |

Use only SQL evidence supplied by the execution layer. Mark whether it ran against the read-only source, private store, or scoped operational projection. Show placeholders in parameterised SQL and a separate parameter list; sensitive values are masked, including private profile predicates. A technical query must not leak disallowed fields through its output or error.

SQL tab: query ID, actual statement, safe parameters, duration, result table, row limit/truncation, and scope label. PDF tab: exact used document, page/section, version/applicability, excerpt and reviewed visual-transcription label. An allowlisted policy-only page link may open the relevant PDF page; no local directory browser or arbitrary file URL. Formula tab: inputs, source badges, rule, amount before GST/GST/total, and expected versus recorded distinction.

Evidence is scoped and fetched with the verified principal/session. Old evidence is inaccessible after a role/session change. No unrelated sources added for visual completeness. An answer missing its mandatory sources is withheld as a verification failure.

## 6. PII presentation

The sidebar and normal conversation expose no full customer profile. Profile requests go through the private service. Mask phone/email/licence and omit unnecessary DOB by default. A customer may explicitly request their own authorised fields; a support agent gets only the fields needed for an allowed, specific support operation.

Show **Protected profile access** on a profile response, with scoped SQL evidence and masked parameters. Audit field names/action/outcome on the server; never display other profiles or raw audit logs. Operational IDs and financial records are still protected even though the direct-PII table is separated.

## 7. Responsive, accessible, and failure behaviour

- Desktop: three-column workspace; tablet: sidebar collapses, evidence overlays; mobile: single chat column with accessible drawer buttons.
- Keyboard-accessible controls, visible focus, semantic headings/form labels, labelled icons, and dialog focus trapping/return. Escape closes evidence; it does not discard a request.
- Use an aria-live status area for meaningful worker changes; avoid flooding it with every streamed byte. Honour reduced motion.
- Preserve source text safely; no unsanitised HTML from the model, remarks, or PDFs.
- Empty result, ambiguous reference, unknown permitted record, unavailable policy, model rate limit, authentication failure, and source-verification failure each get actionable plain language. No stack traces or secrets.
- Do not claim a refund/payment action occurred: the app only answers and explains.

## 8. Timebox and UI acceptance

Implement the shell and session controls first, then one verified answer/evidence path, then worker status streaming. Keep routing/evidence/profile controls and basic keyboard accessibility mandatory. Remove charts, export buttons, rich animations, persistent history, and advanced PDF highlighting from the three-hour target.

UI passes when the verified evaluator can use either role, start/reset a conversation, see real routed workers, inspect the actually executed SQL/PDF behind every substantive answer, and switch sessions without old evidence appearing. Test desktop and a narrow viewport once after final UI changes.

References: [SKOPE workspace pattern](https://github.com/sanmitra-b/SKOPE), [NeoStats visual reference](https://www.neostats.ai/), [Firebase custom authentication](https://firebase.google.com/docs/auth/web/custom-auth), [ID-token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens), [claims and server enforcement](https://firebase.google.com/docs/auth/admin/custom-claims), and [in-memory authentication persistence](https://firebase.google.com/docs/auth/web/auth-state-persistence).
