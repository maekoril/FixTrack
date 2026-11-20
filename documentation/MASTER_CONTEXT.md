# FixTrack Master Context

**Baseline:** November 9, 2026. Implementation verified against commit `1932d45` on `feat/service-requests`. Check your checkout before relying on the status below.

## Purpose and users

FixTrack is a browser-based maintenance and service request system for organizations with multiple branches. It replaces paper forms, phone calls, and separate group chats with a shared record of equipment and facility issues. Staff can see who is responsible, which repairs are urgent or unresolved, what work was done, and how much it cost. The intended repair history supports workload and delay reviews, identification of recurring equipment problems, and repair-versus-replacement decisions.

The original November 2026 proposal was prepared for Laguna State Polytechnic University, College of Computer Studies. FixTrack is a standalone project. Its initial prototype assumes network connectivity and runs in desktop and mobile browsers.

| Role | Available on the baseline branch | Intended responsibilities beyond the baseline |
| --- | --- | --- |
| Branch Manager | Report equipment or facility issues, attach optional photos, and track their own requests through verified closure. | |
| Administrator | Manage branch accounts, triage requests, assign work, verify and close repairs, or return repairs with follow-up instructions. View branch workload, repair and cost reports, and asset repair history. | |
| Technician | Start and complete initial and follow-up work orders. Record diagnosis, progress, repair actions, labor and materials costs, and repair photos. | Review asset repair history. |

## Workflow and scope

See [Lifecycle and debugging guide](SYSTEM_LIFECYCLE.md) for the full role handoffs, review
findings, validation coverage, and current policy gaps.

**Available today.** An administrator creates a Branch Manager account under **People & branches** and grants it one or more branches. The branch manager opens **Report an issue** and submits the branch, title, description, and location. A registered asset in the same branch is optional, so general facility concerns can be submitted independently. The request starts as `submitted`; current intake confirms category and priority, while legacy API submissions can leave them unset. In **Service requests**, the administrator reviews it and chooses `low`, `medium`, `high`, or `urgent`. The branch manager can see that change in the activity history. Triage leaves the request status at `submitted`.

**Service categories.** During triage, administrators can set, change, or clear a category on an open request in a branch they can access. New and existing requests without a category display **Uncategorized**. The shared list includes Electrical, Plumbing, Air Conditioning & Ventilation, IT & Network, Equipment Repair, Building & Facilities, Carpentry, Civil & Structural, Pest Control, Cleaning & Sanitation, and Other. Users can see the category in requests they can access, and administrators can filter the queue by category or **Uncategorized**. Category changes appear in the request history and commit in the same transaction as the update. The category belongs to the request and applies to its initial and follow-up work orders.

**Service estimates.** Administrators can set Easy, Moderate, or Hard difficulty and an estimated duration on open requests in their branches. Difficulty is independent of priority. When both category and difficulty are set, the server suggests a duration from built-in defaults. A manual duration of 1 to 10,080 whole minutes takes precedence and survives changes to category and difficulty. Clearing the manual value restores the suggestion when available. Difficulty and duration are optional and do not gate assignment. Users can see the difficulty and effective duration on requests they can access. Estimate edits appear in activity history and are saved atomically with the request.

**Request setup.** Administrators use one form to save priority, category, difficulty, service duration,
initial assignment or active team changes, schedule, and price estimate. Each save applies the
submitted changes and activity events in one transaction. Admin queue rows and the selected request
show **Needs setup** while an active request is missing any of those planning details. Administrators
can save partial progress. Verification and return for follow-up remain separate workflow actions.
The save response reports the current missing fields. The UI confirms either **Setup complete**
or **Setup saved. Still needed: …**, and queue rows show the specific remaining fields. A saved
active request with all planning details shows a green **Setup complete** badge. Saving setup does
not start repairs: the assigned lead still chooses **Start work**. Form validation identifies
incomplete entries before submission. Unchanged itemized prices do not trigger recalculation
during unrelated partial planning edits; saved price snapshots remain until edited/recalculated.

**Technician specialization.** In **People & branches**, administrators can set, change, or clear one optional specialization for a technician account they manage. The options come from the shared service categories. Initial assignment, reassignment, and follow-up show technicians' specializations and list category matches first. Any active technician with access to the request's branch is eligible. Existing specialization text is preserved, and a matching category name is recognized regardless of case.

**Work order teams and scheduling.** An administrator can assign one lead and optional supporting technicians to an initial or follow-up work order. The lead starts work and submits it for verification. Supporting technicians can see their assignments and add maintenance entries and repair photos while the order is in progress. Administrators can change the lead or edit the supporting team on an active order. A scheduled slot has a start and end time. Saving a schedule requires a future start time. The administrator can enter a duration or use the request estimate. The saved slot stays fixed until edited. Scheduling and team changes check for overlapping active work orders for every assigned technician, including across branches. Branch managers see the latest work order's appointment on their own request.

**Price estimates.** For an active work order, an administrator enters a peso hourly labor rate per technician and estimated materials. FixTrack multiplies the hourly rate by the scheduled or estimated duration and the team size, rounds labor to cents, and adds estimated materials. The administrator can override the suggested total with a reason. Each saved estimate records the calculation inputs. Administrators can recalculate it after a planning change. The lead enters actual labor and materials costs at completion, and reports use those actuals.

**Itemized budgets and approval.** New estimates record up to 100 material lines with item name,
positive quantity (up to three decimal places), unit price, and price source. The server rounds
each material subtotal to cents before summing it. Existing estimates with a single materials
total remain editable and can be replaced with line items. Saving an estimate creates a numbered
draft version when its inputs change. Administrators explicitly approve a saved version; the
approval preserves its calculation inputs, materials, total, approver, and approval time. A later
draft leaves the last approved budget in place until the administrator approves the replacement.
Price and approval events retain the previous snapshots in request history. Branch managers do
not receive these private cost events. Approval uses the displayed version to reject stale actions.
At completion, the lead must explain actual totals above the last approved budget. Administrators
and assigned technicians see approved versus actual totals and the overrun explanation. Existing
workflows without an approved budget remain available, with comparison shown as unavailable.
The administrator still verifies or returns the repair; budget approval does not verify the work.
Technicians see budget changes and approvals in activity history only for work orders on which
they are currently a lead or supporting technician, including when a follow-up has a different team.
Saving a maintenance entry or repair photo keeps other draft fields on the same work order.
**AI request intake.** Reporters can review AI routing before creating a ticket. Groq supports
English, Tagalog, and Taglish, proposes editable category/priority and safety flags, normalizes
reports into English, and analyzes optional photos. Vague reports receive at most three questions
per round and two rounds; unresolved reports are saved as **Incomplete info** after confirmation.
Analysis alone never creates a ticket. People can continue manually before analysis or after a
provider failure. Short reports such as “sira po” are accepted. Technician views default to the
normalized text under **Description**, with follow-up answers collapsed by default. Original text
is available under **Original report** when the normalized description differs. Authorized users open **Edit** to change category and priority;
the form and AI confidence notes stay hidden until editing. Category and priority are otherwise
shown in the request summary. Branch managers add issue photos through a plus tile beside existing
thumbnails; choosing a file uploads it immediately with progress and error feedback. The plus tile
opens the browser's file chooser for a JPEG, PNG, or WebP on desktop or mobile.

Intake photos are limited to 5 MB/24 megapixels, checked as JPEG/PNG/WebP, stripped of metadata,
and resized to at most 1024 pixels before transfer. Only attached photos use the configured
Groq vision model (`qwen/qwen3.8-27b`); text uses `GROQ_MODEL`. Recognized emails, Philippine
mobile numbers, and explicit name introductions are redacted from text, without guaranteeing
exhaustive personal-data removal. Provider attempts use a 15-second timeout, retry once, and fall
back to manual intake. Five analyses per account per minute are allowed by default; PostgreSQL
account-row locks serialize reservations. Token counts/outcomes are recorded without logging text.

Server-owned intake snapshots preserve original/normalized text, AI and final routing, overrides,
photo observations, Q&A, confidence, and validated source JSON. Submission rejects snapshots from
another account/branch, changed source text, unanswered follow-ups, or reused snapshots. Branch
managers can revise intake routing on their own accessible reports and administrators on accessible
reports, including after closure. Existing admin planning edits also synchronize the final values.
Changes append history; safety flags remain highlighted after an override. A safety event is saved
with submission and shown to the reporting manager (including their own action) and scoped admins
through the existing inbox/polling. Other branch managers' visibility remains unchanged.
See [AI intake implementation and tests](AI_INTAKE.md) for contracts and category mapping.

**AI estimate assistant.** Administrators can generate repair tasks, proposed material quantities
and units, service duration, assumptions, and missing-information prompts for active requests.
The backend calls Groq's Chat Completions API using a configured server-side key and a strict JSON
schema. It sends saved issue details, category, difficulty, optional equipment name/condition, and
the latest ten maintenance notes (each capped at 2,000 characters). Account identities, branch
names, location fields, and photos are excluded from the assembled context; free-text issue and
maintenance content is sent as entered. The interface describes the data sent before generation.
Suggestions are temporary and do not save or approve budgets. Administrators can explicitly copy
the suggested service duration and add proposed materials to the form, then supply verified unit
prices and sources before saving. Existing scheduled slots remain fixed. Replacing legacy
materials totals is explicitly labeled. AI does not supply peso prices or verify completed repairs.
Missing configuration, provider errors, refusals, or invalid output leave manual estimation available.
An intermittent strict-generation rejection from Groq triggers one fallback call in JSON-object
mode. The same local schema validation applies before returning a suggestion. Model, quota,
credential, and other errors are not retried. Provider messages and failed generations are not
forwarded to clients or logs; only HTTP status and recognized error codes are logged.
Receipt extraction and AI evidence review remain future work.

The estimate assistant uses a compact summary and duration card with explicit copy actions.
Material details, repair tasks, assumptions, missing information, and the full data-transfer
disclosure expand on demand. Failed regeneration preserves the previous plan and its copied
state, so a provider error does not discard usable suggestions or re-enable duplicate imports.

**Repair lifecycle.** The administrator reviews the latest completed work order and can verify and close the request with optional notes. Returning the repair requires instructions and an active technician in the request's branch. The request moves back to `in_progress` and a new assigned work order is created in the same transaction. Completed orders retain their logs and costs. Branch managers can follow the decision in the request history.

While a repair awaits verification, request setup and intake routing are read-only. The server
rejects changes to priority, category, difficulty, and duration, including direct API edits.
Administrators can verify the repair or return it for follow-up; returning reopens planning
for the new work order while preserving the completed order.

- Request states modeled in the schema: `submitted → in_progress → awaiting_verification → closed`.
- Work-order states modeled in the schema: `assigned → in_progress → completed`.
- The active API handles submission, priority changes, initial assignment, starting work, maintenance entries, and technician completion. Administrators assign a submitted request with no existing work order to an active technician with access to its branch. The work order starts as `assigned` and the request stays `submitted`. In **Assigned requests**, the assigned technician can see the work-order status and choose **Start work**. This changes both records to `in_progress` and adds an activity event in the same transaction. While work is in progress, the technician can append diagnosis, progress, and repair entries. Completing work saves labor and materials costs, marks the order completed, moves the request to awaiting verification, and adds one completion event in the same transaction. Administrators can review logs and costs. Branch managers can read technician maintenance entries on their own accessible requests, including prior work orders, and follow completion in the activity history.

Administrators can reassign an assigned or in-progress work order to another active technician with branch access. Reassignment requires a reason and records the previous and new technician in the request history. The new technician inherits the order's status and maintenance history.

The in-app inbox uses request events and stores read state per account. Administrators receive new
reports and completion alerts, technicians receive assignments and follow-ups, and branch managers
receive updates on their own reports. The floating inbox filters by Approvals, Updates, or Completed.
An administrator’s approval notification moves to Completed when that work order no longer awaits
verification. The double-check icon beside Close marks the entire inbox as read, regardless of
the selected filter. Opening a notification marks it as read and opens its request.
Inbox queries enforce current request access. Visible tabs refresh the inbox, request queue, and
open request every five seconds.

The administrator Dashboard counts requests needing assignment, urgent open requests, work orders
in progress, and repairs awaiting verification. It uses current branch grants and links each count
to the matching request queue. The verification count links to completed work, and
the urgent list opens individual requests. Counts and up to four urgent requests refresh every
five seconds while the tab is visible. Administrators can pause and resume overview updates;
the displayed update time shows the last successful refresh.

Administrators can open **Reports** to compare verified closures, completed work orders, and
labor, materials, and total repair costs across their accessible branches. The report uses an
inclusive UTC date range. Closures use the verification date. Work orders, including follow-ups,
use their recorded completion date.

**Next development milestone.** Technician access to asset repair history.

Administrators can register and edit branch equipment in Assets, search by tag or name, and
view linked request and work-order history with total recorded repair costs. Existing assets
receive an empty location through migration. Assets keep their original branch.

The interface uses a collapsible ink-navy sidebar, cool paper surfaces, cobalt-violet controls,
and coral for urgent requests. The overview uses a compact KPI strip and links to the asset
registry. The header keeps notifications and account options in two compact controls. The account
menu shows the current role and opens a sign-out confirmation. Successful sign-out displays a
brief toast on the sign-in page. Administrators can search and filter managed accounts, expand a row to edit
name/email, branch access, or specialization, and confirm account status changes. Account actions
also offer permanent deletion in a small centered confirmation modal naming the account. Only accounts without
recorded activity can be deleted; accounts linked to requests, assignments, or other records return
a conflict and must be disabled instead. Failed deletion restores branch grants. Administrators
and accounts outside the acting administrator's complete branch scope remain protected. Branch and account creation use
drawers. Date displays use abbreviated month names and repair costs use Philippine peso formatting.
Reduced-motion preferences disable animated transitions and KPI counts.

**Future expansion.** Preventive maintenance scheduling, asset QR codes, email or SMS notifications, service targets and escalation, spare-parts inventory, purchase requests, external service providers, offline mobile capture and synchronization, and longer-term recurring-failure and replacement analysis.

## Authorization and activity rules

- The server enforces role and current branch grants. `branch_access` is explicit for all roles, including administrators. Revocation applies to subsequent protected calls even with an unexpired token.
- Branch managers can submit only to granted branches and see only their own requests in branches they can still access. Administrators see requests in their granted branches. Technicians need both current branch access and a linked work order assigned to them.
- Administrator account controls apply only to branch managers and technicians whose entire branch grant set is within the acting administrator's scope. Both roles require one or more branches. The role migration converts existing employees and retains their grants and history. Administrators can grant only branches they already hold. Creating a branch grants the creator access. The current UI supports branch creation. Branch rename and deletion are outside the current interface.
- The first administrator can be provisioned through the browser with an optional setup token. Browser provisioning closes once an administrator exists. The bootstrap CLI can also provision administrators. The management API creates, reassigns and enables or disables branch manager and technician accounts. A disabled account cannot sign in or reuse an issued token. Accounts use Argon2 password hashing and expiring JWT bearer tokens with a 30-minute default. The React client keeps tokens in memory. Refresh requires sign-in, and client sign-out clears local session state while an issued token remains valid until expiry, subject to account and permission checks.
- Missing and out-of-scope request IDs return the same 404. A closed request returns 409 on reprioritization. Priority updates lock the request row and record an event only when the value changes. Submission and priority events commit in the same transaction as their corresponding changes. Keep future request events and maintenance logs append-only in application operations.
- Issue and repair photos are private. Branch managers upload to their own open requests, and technicians upload while working on an assigned order. Both thumbnails and larger images require current access to the parent request. The server re-encodes images as JPEG without original metadata and stores both sizes in PostgreSQL.

## Architecture and data

The proposal groups the product into Core/User Management, Request Management, Work Order Management, Asset Management, Cost Tracking, and Reporting & Dashboard. Core supplies identity and branch access. Work orders build on requests, costs are recorded against work orders, and reporting reads operational records. These are product modules with a shared backend and database.

- **Frontend:** React, TypeScript and Vite with plain CSS. `frontend/src/main.tsx` owns sign-in, in-memory session state and workspace navigation. `Admin.tsx` renders People & branches, `Requests.tsx` renders issue reporting and triage, `Reports.tsx` renders repair reports, `Dashboard.tsx` renders the overview, and `Assets.tsx` renders the equipment registry. `style.css` holds base component styles and `workspace.css` holds the shared visual theme and responsive layouts.
- **Backend:** Python 3.14, FastAPI, Pydantic, SQLAlchemy and Alembic. `backend/app/main.py` wires the app and health, auth and branch routes. `security.py` handles tokens and current user checks. `admin.py` implements account and branch management. `requests.py` contains scoped queries, request payloads, event history and triage. `bootstrap.py` provisions an administrator with a privately prompted password.
- **Storage:** PostgreSQL 17, UUIDs, timezone-aware timestamps and decimal money fields. Schema changes go through Alembic. Server startup does not create tables or default accounts.

| Records | Relationships and decisions |
| --- | --- |
| `branches`, `users`, `branch_access` | A single user table represents all three roles. A join table grants branches. Users have a unique email, activation flag, and optional specialization. |
| `assets`, `service_requests` | Assets have a unique tag, branch and condition. Requests have a branch, submitter, location, nullable priority and optional asset. A composite foreign key enforces same-branch asset references. Closure fields capture who closed a request and when. |
| `service_categories` | The migration seeds shared categories with stable IDs. Requests reference one optional category. |
| `work_orders`, `work_order_assistants`, `maintenance_logs` | A request may have many work orders. Each stores the lead and assigning user, work status, optional schedule and price estimate, and actual labor and materials costs. A join table links supporting technicians. Maintenance logs store the recorder, action, notes, and timestamp. |
| `request_events`, `attachments` | Events store a request, actor, action, timestamp and structured details. Attachments store a parent request, optional work order, uploader, original filename, and private image and thumbnail bytes. |

The proposal's production topology is browser → HTTPS web gateway → FastAPI → private PostgreSQL, with a private volume for photos. The gateway serves the frontend and proxies `/api`. Separate branch subnets with site-to-site IPsec VPNs are an illustrative deployment option. Local development demonstrates the workflows on one computer. Production hardening still includes login throttling, session and recovery policy, secrets, HTTPS and reverse-proxy configuration, attachment validation, backups, and monitoring.

## API map

| Area | Available endpoints |
| --- | --- |
| Health and identity | `GET /api/health`, `GET /api/ready`, `POST /api/auth/login`, `GET /api/auth/me`, `GET /api/branches` |
| Initial setup | `POST /api/setup/admin` with `X-Setup-Token` when browser setup is enabled |
| Notifications | `GET /api/notifications` with optional `category` (`approval`, `update`, or `completed`). `PUT /api/notifications/read` marks the entire inbox as read. `PUT /api/notifications/{event_id}/read` marks one item. |
| Photos | `POST /api/requests/{request_id}/photos`, `GET /api/requests/{request_id}/photos/{photo_id}` with optional `thumbnail=true` |
| Administrator dashboard | `GET /api/requests/dashboard` with optional `branch_id`. Queue links use `focus` on `GET /api/requests`. |
| Administrator reports | `GET /api/reports/repairs` with required `start_date` and `end_date` and optional `branch_id`. |
| Administrator | `POST /api/admin/branches`, `GET /api/admin/users`, `POST /api/admin/users`, `PUT /api/admin/users/{user_id}/branches`, `PATCH /api/admin/users/{user_id}/active`, `PATCH /api/admin/users/{user_id}/specialization` with a category ID or null |
| Technician progress | `POST /api/requests/{request_id}/work-orders/{work_order_id}/logs`, `POST /api/requests/{request_id}/work-orders/{work_order_id}/complete` |
| Administrator repair review | `POST /api/requests/{request_id}/verify`, `POST /api/requests/{request_id}/return` |
| Administrator service categories | `GET /api/requests/categories`, `PATCH /api/requests/{request_id}/category` with a category ID or null. The request list accepts `category_id`, including `uncategorized`. |
| Administrator service estimates | `PATCH /api/requests/{request_id}/estimate` with nullable `difficulty` and `duration_override_minutes`. Request responses include the suggested and effective duration in minutes. |
| Administrator request setup | `PATCH /api/requests/{request_id}/setup` saves triage and work order planning changes in one transaction. Admin list and detail responses identify missing setup information. |
| Administrator work order planning | `PATCH /api/requests/{request_id}/work-orders/{order_id}/team`, `/schedule`, and `/price` edit the supporting team, planned slot, and price estimate. Initial and follow-up assignment accept optional `assistant_ids`. |
| Budget approval | `POST /api/requests/{request_id}/work-orders/{order_id}/price/approve` accepts the displayed estimate `version`. Price input accepts optional `materials_items` (name, quantity, unit_price, source); the server derives materials totals when provided. Completion accepts `overrun_reason`, required above the approved total. |
| AI intake | `POST /api/requests/triage` accepts JSON or multipart with an optional image and returns a result/snapshot or manual fallback. `PATCH /api/requests/{id}/triage-confirmation` confirms routing under current access. Lists accept `ai_overridden=true/false`. |
| AI estimate assistance | Administrator-only `POST /api/requests/{request_id}/ai/estimate` returns suggestions for a currently accessible submitted or in-progress request. Requires backend `GROQ_API_KEY`; `GROQ_MODEL` defaults to `openai/gpt-oss-20b`, hosted by Groq. |
| Service requests | `POST /api/requests`, `GET /api/requests`, `GET /api/requests/assets?branch_id=…`, `GET /api/requests/{request_id}`, `PATCH /api/requests/{request_id}/priority`, `POST /api/requests/{request_id}/work-orders`, `POST /api/requests/{request_id}/work-orders/{work_order_id}/start` |

The request list searches titles case-insensitively and supports branch, status and priority filters. It sorts newest first and uses offset pagination with a default limit of 25 and a maximum of 100. Detail responses include activity in chronological order. Submission trims and validates title, description and location. See route schemas or Swagger for payload details.

Intake storage uses `request_intakes` for pending/linked provenance snapshots and `intake_attempts` for per-user rate reservations and token usage. Migration `e40d51a6b902` adds these tables and four registry categories.

## Local development and collaboration

- Use Python 3.14, Node.js 24 LTS, npm, Git, and Docker Compose or a local PostgreSQL 17 installation. With Compose, run `docker compose up -d db` from the root.
- Follow the [README](../README.md) for virtual environment setup, `backend/.env` configuration, `alembic upgrade head`, and the first-administrator browser form at `/#setup`. Run backend commands from `backend/` so settings can load `.env`. Use a unique `JWT_SECRET`. Keep credentials, tokens, database dumps and issue photos out of Git.
- Start FastAPI with `python -m uvicorn app.main:app --reload --host 127.0.0.1` from `backend/`. Run `npm ci` and `npm run dev` from `frontend/`. Vite serves the UI on port 5173 and proxies the API to port 8000. FastAPI serves Swagger at `/docs`.
- Use `backend/requirements.txt` and `frontend/package-lock.json` for reproducible installs. Run pytest, Ruff lint and format checks, Alembic drift checks, and the frontend build as relevant. Backend tests use SQLite with foreign keys for fast checks. CI exercises migration upgrade, drift detection, rollback and reapplication against PostgreSQL. Extend PostgreSQL coverage as transactional workflows are added.
- Coordinate issues and migrations, keep pull requests focused, and use reviews and passing CI before merging. Add a new migration for schema changes after a revision has been applied. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## History and source map

- Git remote: `maekoril/FixTrack`. At the baseline, local refs showed `main` and `origin/main` at `5fd2c88` (foundation). `35cfd66` added branch-scoped administrator controls. `1932d45` added employee requests and administrator triage and was pushed on `feat/service-requests`. Confirm the active branch and merge status before starting follow-up work.
- The request milestone recorded 27 passing backend tests, a successful frontend build, a PostgreSQL migration drift check, and a browser smoke test covering employee submission, administrator priority updates and desktop/mobile layout. This is historical validation for the baseline.
- [Original project proposal](FixTrack_Project_Proposal.pdf) contains the problem statement, UML, intended scope, production topology and future expansion. [Development notes](DEVELOPMENT.md) explain implemented API behavior, architecture decisions and milestones. [README](../README.md) covers setup and the available workflow. Consult the current code, migrations, tests and Git history for live implementation details.
