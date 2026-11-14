# FixTrack Master Context

**Baseline:** November 9, 2026. Implementation verified against commit `1932d45` on `feat/service-requests`. Check your checkout before relying on the status below.

## Purpose and users

FixTrack is a browser-based maintenance and service request system for organizations with multiple branches. It replaces paper forms, phone calls, and separate group chats with a shared record of equipment and facility issues. Staff can see who is responsible, which repairs are urgent or unresolved, what work was done, and how much it cost. The intended repair history supports workload and delay reviews, identification of recurring equipment problems, and repair-versus-replacement decisions.

The original November 2026 proposal was prepared for Laguna State Polytechnic University, College of Computer Studies. FixTrack is a standalone project. Its initial prototype assumes network connectivity and runs in desktop and mobile browsers.

| Role | Available on the baseline branch | Intended responsibilities beyond the baseline |
| --- | --- | --- |
| Branch Manager | Report equipment or facility issues, attach optional photos, and track their own requests through verified closure. | |
| Administrator | Manage branch accounts, triage requests, assign work, verify and close repairs, or return repairs with follow-up instructions. View branch workload from the Dashboard. | Review cost trends and asset repair history. |
| Technician | Start and complete initial and follow-up work orders. Record diagnosis, progress, repair actions, labor and materials costs, and repair photos. | Review asset repair history. |

## Workflow and scope

**Available today.** An administrator creates a Branch Manager account under **People & branches** and grants it one or more branches. The branch manager opens **Report an issue** and submits the branch, title, description, and location. A registered asset in the same branch is optional, so general facility concerns can be submitted independently. The request starts as `submitted` with priority unset. In **Service requests**, the administrator reviews it and chooses `low`, `medium`, `high`, or `urgent`. The branch manager can see that change in the activity history. Triage leaves the request status at `submitted`.

**Repair lifecycle.** The administrator reviews the latest completed work order and can verify and close the request with optional notes. Returning the repair requires instructions and an active technician in the request's branch. The request moves back to `in_progress` and a new assigned work order is created in the same transaction. Completed orders retain their logs and costs. Branch managers can follow the decision in the request history.

- Request states modeled in the schema: `submitted → in_progress → awaiting_verification → closed`.
- Work-order states modeled in the schema: `assigned → in_progress → completed`.
- The active API handles submission, priority changes, initial assignment, starting work, maintenance entries, and technician completion. Administrators assign a submitted request with no existing work order to an active technician with access to its branch. The work order starts as `assigned` and the request stays `submitted`. In **Assigned requests**, the assigned technician can see the work-order status and choose **Start work**. This changes both records to `in_progress` and adds an activity event in the same transaction. While work is in progress, the technician can append diagnosis, progress, and repair entries. Completing work saves labor and materials costs, marks the order completed, moves the request to awaiting verification, and adds one completion event in the same transaction. Administrators can review logs and costs. Branch managers can read technician maintenance entries on their own accessible requests, including prior work orders, and follow completion in the activity history.

Administrators can reassign an assigned or in-progress work order to another active technician with branch access. Reassignment requires a reason and records the previous and new technician in the request history. The new technician inherits the order's status and maintenance history.

The in-app inbox uses request events and stores read state per account. Administrators receive new
reports and completion alerts, technicians receive assignments and follow-ups, and branch managers
receive updates on their own reports. Inbox queries enforce current request access. Visible tabs
refresh the inbox, request queue, and open request every five seconds.

The administrator Dashboard counts requests needing assignment, urgent open requests, work orders
in progress, and repairs awaiting verification. It uses current branch grants and links each count
to the matching request queue. A prominent verification panel links to completed work, and
the urgent list opens individual requests. Counts and up to four urgent requests refresh every
five seconds while the tab is visible. Administrators can pause and resume overview updates;
the displayed update time shows the last successful refresh.

**Delivery order from the development plan**

1. Expanded cost summaries and asset reporting.

Administrators can register and edit branch equipment in Assets, search by tag or name, and
view linked request and work-order history with total recorded repair costs. Existing assets
receive an empty location through migration. Assets keep their original branch.

The interface uses ink navigation, ivory surfaces, maintenance amber accents, condensed
display headings, and consistent line icons. The overview pairs a prominent verification
panel with operational counts and urgent requests. Shared styles cover sign-in, requests,
assets, and account management, with responsive layouts and short entrance, selection,
and hover transitions. Reduced-motion preferences disable animations and transitions.

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

- **Frontend:** React, TypeScript and Vite with plain CSS. `frontend/src/main.tsx` owns sign-in, in-memory session state and workspace navigation. `Admin.tsx` renders People & branches, `Requests.tsx` renders reporting and triage, `Dashboard.tsx` renders the overview, and `Assets.tsx` renders the equipment registry. `style.css` holds base component styles and `workspace.css` holds the shared visual theme and responsive layouts.
- **Backend:** Python 3.14, FastAPI, Pydantic, SQLAlchemy and Alembic. `backend/app/main.py` wires the app and health, auth and branch routes. `security.py` handles tokens and current user checks. `admin.py` implements account and branch management. `requests.py` contains scoped queries, request payloads, event history and triage. `bootstrap.py` provisions an administrator with a privately prompted password.
- **Storage:** PostgreSQL 17, UUIDs, timezone-aware timestamps and decimal money fields. Schema changes go through Alembic. Server startup does not create tables or default accounts.

| Records | Relationships and decisions |
| --- | --- |
| `branches`, `users`, `branch_access` | A single user table represents all three roles. A join table grants branches. Users have a unique email, activation flag, and optional specialization. |
| `assets`, `service_requests` | Assets have a unique tag, branch and condition. Requests have a branch, submitter, location, nullable priority and optional asset. A composite foreign key enforces same-branch asset references. Closure fields capture who closed a request and when. |
| `work_orders`, `maintenance_logs` | A request may have many work orders. Each stores the technician and assigning user, work status, and separate nonnegative labor and materials costs. Maintenance logs store the recorder, action, notes, and timestamp. |
| `request_events`, `attachments` | Events store a request, actor, action, timestamp and structured details. Attachments store a parent request, optional work order, uploader, original filename, and private image and thumbnail bytes. |

The proposal's production topology is browser → HTTPS web gateway → FastAPI → private PostgreSQL, with a private volume for photos. The gateway serves the frontend and proxies `/api`. Separate branch subnets with site-to-site IPsec VPNs are an illustrative deployment option. Local development demonstrates the workflows on one computer. Production hardening still includes login throttling, session and recovery policy, secrets, HTTPS and reverse-proxy configuration, attachment validation, backups, and monitoring.

## API map

| Area | Available endpoints |
| --- | --- |
| Health and identity | `GET /api/health`, `GET /api/ready`, `POST /api/auth/login`, `GET /api/auth/me`, `GET /api/branches` |
| Initial setup | `POST /api/setup/admin` with `X-Setup-Token` when browser setup is enabled |
| Notifications | `GET /api/notifications`, `PUT /api/notifications/{event_id}/read` |
| Photos | `POST /api/requests/{request_id}/photos`, `GET /api/requests/{request_id}/photos/{photo_id}` with optional `thumbnail=true` |
| Administrator dashboard | `GET /api/requests/dashboard` with optional `branch_id`. Queue links use `focus` on `GET /api/requests`. |
| Administrator | `POST /api/admin/branches`, `GET /api/admin/users`, `POST /api/admin/users`, `PUT /api/admin/users/{user_id}/branches`, `PATCH /api/admin/users/{user_id}/active` |
| Technician progress | `POST /api/requests/{request_id}/work-orders/{work_order_id}/logs`, `POST /api/requests/{request_id}/work-orders/{work_order_id}/complete` |
| Administrator repair review | `POST /api/requests/{request_id}/verify`, `POST /api/requests/{request_id}/return` |
| Service requests | `POST /api/requests`, `GET /api/requests`, `GET /api/requests/assets?branch_id=…`, `GET /api/requests/{request_id}`, `PATCH /api/requests/{request_id}/priority`, `POST /api/requests/{request_id}/work-orders`, `POST /api/requests/{request_id}/work-orders/{work_order_id}/start` |

The request list searches titles case-insensitively and supports branch, status and priority filters. It sorts newest first and uses offset pagination with a default limit of 25 and a maximum of 100. Detail responses include activity in chronological order. Submission trims and validates title, description and location. See route schemas or Swagger for payload details.

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
