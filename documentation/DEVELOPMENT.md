# Development architecture and milestones

## Foundation decisions

- React + TypeScript + Vite frontend; FastAPI + SQLAlchemy backend; PostgreSQL 17 database.
- UUID primary keys, UTC timestamps, and decimal money fields.
- One user table with branch manager, technician, and administrator roles. `branch_access` grants
  explicit access to branches for every role. Branch managers and technicians need at least one assigned branch.
- Assets and service requests belong to a branch. A composite foreign key prevents a request
  from referencing an asset from another branch. General facility requests need no asset.
- A request can have multiple work orders. Each work order has one technician, labor and material
  costs, and maintenance logs. Request events record the actor and changes.
- Photos are stored in PostgreSQL with their thumbnails. Uploads and downloads enforce current
  access to the parent request. Accepted images are decoded and re-encoded without source metadata.
- Passwords use Argon2; short-lived signed bearer tokens identify the current user. Account
  activation and current permissions are read from the database on protected requests.
- The frontend keeps its bearer token in React state for administrator operations. Refresh
  requires signing in again. Tokens are never persisted in localStorage or sessionStorage.
- No public registration, default accounts, or automatic schema creation at server startup.

## Implemented endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Process liveness |
| `GET /api/ready` | Database connectivity |
| `POST /api/auth/login` | JSON email/password to expiring bearer token |
| `GET /api/auth/me` | Authenticated profile |
| `GET /api/branches` | Branches explicitly granted to the current user |
| `POST /api/admin/branches` | Create a branch and grant the creating administrator access |
| `GET/POST /api/admin/users` | List managed users or create branch manager or technician accounts |
| `PATCH /api/admin/users/{id}` | Edit a managed account's full name and email |
| `DELETE /api/admin/users/{id}` | Delete a managed account without recorded activity; otherwise return 409 |
| `PUT /api/admin/users/{id}/branches` | Replace a managed user's branch access |
| `PATCH /api/admin/users/{id}/active` | Disable or enable a managed account |
| `POST /api/requests` | Branch manager submission with optional registered asset |
| `GET /api/requests` | Scoped list with search, branch/status/priority filters and pagination |
| `GET /api/requests/assets?branch_id=...` | Registered assets for an accessible branch |
| `GET /api/requests/{id}` | Scoped request details and activity history |
| `PATCH /api/requests/{id}/priority` | Administrator triage with transactional history |
| `POST /api/requests/{id}/work-orders` | Assign an initial work order using `technician_id` |
| `POST /api/requests/{id}/work-orders/{work_order_id}/start` | Start an assigned work order as its technician |
| `POST /api/requests/{id}/work-orders/{work_order_id}/logs` | Append an action and notes to an in-progress work order |
| `POST /api/requests/{id}/work-orders/{work_order_id}/complete` | Save costs and submit the work for verification |
| `GET /api/reports/repairs` | Report branch totals for verified closures, completed work orders, labor, materials, and combined costs |

Administrator tools manage only branch managers and technicians whose complete branch access is
within the administrator's scope. Both roles may have multiple branches.
Administrators cannot grant branches they do not have. Administrator accounts are
provisioned through the first-admin browser setup or the bootstrap CLI. Management endpoints create,
edit, enable/disable, and delete branch manager and technician accounts. Profile edits retain roles,
passwords, and branch grants and reject duplicate emails. Deletion removes branch grants and the
account atomically; existing foreign keys block deletion when requests, assignments, logs, intake,
or other recorded activity refer to the user. A blocked delete returns 409 and restores grants;
administrators can disable the account instead. The UI confirms permanent deletion before sending
the request. Deleted accounts cannot reuse existing login tokens. No migration is required.
Creating a new branch grants the creator access. The current interface lets administrators
create branches but does not rename or remove existing branches.

Branch managers see only their own requests and only while they retain branch access. Administrators
see requests in their granted branches; technicians see only requests linked to work orders
assigned to them, also subject to branch access. Missing and inaccessible request IDs return
the same 404 response. Administrators can assign an initial work order to an active technician
with access to the request's branch. Request details include eligible technicians for administrators
when assignment is available. Assignment requires a submitted request without a work order and
leaves the request status at `submitted`. Technician request details include their work orders.
The assigned technician can start work while they have branch access. Starting work moves the
order and request to `in_progress` and records a history event in the same transaction. Repeating
the start while both are in progress returns the existing state without adding another event. Completion records nonnegative labor and materials amounts with up to two decimal places. Costs, the completed work order, the request awaiting verification, and its completion event commit together. Retrying completion with the same costs returns the saved order. Administrators and the assigned technician can read the logs and costs. Branch managers can see the maintenance history, request status, and completion event for their own accessible requests. Work-order costs remain visible to administrators and assigned technicians.
Request lists default to 25 records with a maximum of 100 and support an offset.
The asset selector reads branch registry records. Administrators use `GET/POST /api/assets`,
`GET /api/assets/{id}`, and `PATCH /api/assets/{id}` for registration, editing, and repair history.
Asset history and cost totals follow current administrator branch grants.

## Next milestones

1. Technician access to asset repair history.

Repair reports accept inclusive UTC calendar dates as `start_date` and `end_date`, plus an
optional `branch_id`. They count verified closures by `closed_at` and completed work orders
by their existing `work_completed` events. An order contributes its costs once, including
when it is a follow-up or its parent request remains open. Only current administrator branch
grants are included. Completed orders without a recorded completion event have no date for
reporting and are omitted from the date-range figures.

Requests move from `submitted` to `in_progress` to `awaiting_verification` to `closed`.
An administrator can send a request back to `in_progress` with instructions and a new work order.
Both review actions require the latest completed work-order ID and lock the request before
changing state and recording the review event in the same transaction.

`POST /api/requests/{id}/work-orders/{work_order_id}/reassign` takes the current
`previous_technician_id`, the replacement `technician_id`, and a reason. It transfers an
active work order in place and records the change in the same transaction.

The notification inbox derives role-specific alerts from request events and uses
`notification_reads` to persist each account's read state. It shows up to 50 accessible alerts,
with unread entries first. Technician alerts use the recipient recorded on each assignment event
and require the technician to still hold that work order. Older assignment and follow-up events
without a recipient ID remain visible in request history. The browser polls every five seconds
while visible and refreshes when the tab becomes visible again.

## Before production

### Budget estimation and review

Admin setup saves return `setup_missing` computed from the committed request and current active
work order. Clients distinguish successful partial saves from complete planning and render the
remaining field names. `frontend/src/planning.ts` compares canonical price inputs, excluding saved
line subtotals and formatting differences, so unchanged itemized quotes do not cause a price write
on an unrelated save. This permits partial planning edits even when a new duration is not yet set.
Run `npm test` in `frontend/` for these save/price regressions, in addition to the backend suite.

Work-order estimates support `materials_items` (up to 100) alongside the legacy
`materials_estimate` input. When itemized input is provided, the server calculates
materials from quantity × unit price, rounds each line half-up to cents, and sums
the rounded amounts. Labor uses the existing duration × team size × hourly rate.
Each changed estimate increments a version in `price_estimate`; legacy estimates
without a version are version 0. Administrators approve the displayed version via
`POST /api/requests/{request_id}/work-orders/{order_id}/price/approve`.

`work_orders.approved_price` stores a separate immutable-in-application snapshot
of the most recent approval. Draft edits do not mutate it. Reapproval replaces
the current snapshot and appends both the old and new snapshots to a request
event. Request and work-order locks serialize estimate approval and completion.
Completion requires an `overrun_reason` when actual labor plus materials exceeds
the approved amount. Older orders without approvals can still complete. Reports
continue to use actual recorded costs, and repair verification remains an explicit
administrator action. Apply migration `d92b34f81a06` before running the updated API.

### AI estimate suggestions

`app/ai.py` exposes administrator-only `POST /api/requests/{id}/ai/estimate`.
Current request access and active planning state are checked before a provider call.
The existing HTTPX dependency calls Groq's Chat Completions API with strict JSON schema,
low reasoning effort, a 4,096-token completion cap,
and configurable per-operation HTTP timeouts (30 seconds by default).
`GROQ_API_KEY` is a backend-only `SecretStr`; `GROQ_MODEL` defaults to `openai/gpt-oss-20b`
and must support Groq's strict structured output and low reasoning effort. The model is
hosted by Groq; the `openai/` model ID prefix does not route requests to OpenAI.
The fixed endpoint is `https://api.groq.com/openai/v1/chat/completions`. System/user
messages carry instructions and request data. Only a stopped completion with valid JSON
content is accepted; truncated completions, refusals, and malformed choices are rejected.
Legacy OpenAI configuration is ignored; keys are never forwarded between providers.
Groq can intermittently reject strict JSON generation with HTTP 400 and code
`json_validate_failed` or `structured_generation_failed`. For these two errors only,
the server makes one fallback call using JSON-object mode with the schema in the
system prompt. Local Pydantic validation remains mandatory. This caps generation at
two calls; credentials, quota, model, timeout, and other errors are not retried.
Logs contain only HTTP status and allowlisted error codes, excluding raw messages,
failed generations, issue content, and keys. Model/configuration and generation
failures produce distinct actionable messages in the UI.

Only saved issue title/description, category, difficulty, optional asset name/condition,
and ten recent maintenance action/notes pairs are assembled for the provider. Each
note is capped at 2,000 characters. Free text may contain whatever users entered;
there is no automatic personal-data redaction. No photos, account identifiers, branch
names, or location fields are added. The UI discloses the transfer before generation.
Responses are validated locally and never written to budgets or request events.
Provider errors and invalid or incomplete results return generic actionable errors
without forwarding raw provider payloads or credentials.

The assistant proposes tasks, duration, material names/quantities/units, assumptions,
and missing information. Its schema excludes monetary fields. Administrators choose
whether to use the duration or add materials; imported material lines require prices
and sources. Approval and completion remain the existing deterministic workflows.
Suggestions are not persisted and there is no cross-request historical price retrieval,
receipt parsing, image analysis, or automatic work verification in this integration.
Tests replace HTTPX transport, so the suite makes no paid provider calls.

Official API references: [quickstart](https://console.groq.com/docs/quickstart),
[structured outputs](https://console.groq.com/docs/structured-outputs).

## AI request intake

The intake implementation is documented in [AI intake](AI_INTAKE.md), including the JSON/multipart
contract, two-round Q&A, original/normalized descriptions, human confirmation, category mapping,
photo privacy, per-user rate limits, provider fallback, migrations, and test instructions.
Apply migration `e40d51a6b902` and install the pinned `python-multipart` dependency before running
the updated API. The existing administrator estimate assistant is separate and unchanged.

### Deployment hardening

CORS permits GET, POST, PUT, PATCH, and DELETE for configured origins. DELETE is required
for the administrator account-deletion endpoint when using a separate frontend origin;
unconfigured origins remain blocked. A preflight regression covers both cases.

This is a development foundation. Add login throttling, a reviewed session/logout and password
recovery policy, deployment secrets, HTTPS/reverse proxy configuration, attachment validation,
backups, and operational monitoring before a public deployment. A client sign-out currently
clears the displayed session; issued API tokens expire after 30 minutes and are not revoked by it.

CI applies, checks, rolls back, and reapplies migrations against PostgreSQL. The fast auth and
constraint tests use SQLite with foreign keys enabled; extend PostgreSQL integration coverage
as transactional workflows are added.
