# FixTrack Master Context

**Baseline:** November 9, 2026. Implementation verified against commit `1932d45` on `feat/service-requests`. Check your checkout before relying on the status below.

## Purpose and users

FixTrack is a browser-based maintenance and service request system for organizations with multiple branches. It replaces paper forms, phone calls, and separate group chats with a shared record of equipment and facility issues. Staff can see who is responsible, which repairs are urgent or unresolved, what work was done, and how much it cost. The intended repair history supports workload and delay reviews, identification of recurring equipment problems, and repair-versus-replacement decisions.

The original November 2026 proposal was prepared for Laguna State Polytechnic University, College of Computer Studies. FixTrack is a standalone project. Its initial prototype assumes network connectivity and runs in desktop and mobile browsers.

| Role | Available on the baseline branch | Intended responsibilities beyond the baseline |
| --- | --- | --- |
| Employee | Report equipment or facility issues and track their own requests and activity within their current branch access. | Attach an optional issue photo and follow the report through verified closure. |
| Administrator | Create branches, manage eligible employee and technician accounts, review requests within granted branches, set priorities, and assign initial work orders. | Verify repair results, return incomplete repairs for more work, close requests, and review branch workload and costs. |
| Technician | View assigned requests and start their assigned work orders within their current branch access. | Record diagnosis, progress and actions, enter labor and material costs, and report completion. |

## Workflow and scope

**Available today.** An administrator creates an employee account under **People & branches** and grants it one branch. The employee opens **Report an issue** and submits the branch, title, description, and location. A registered asset in the same branch is optional, so general facility concerns can be submitted independently. The request starts as `submitted` with priority unset. In **Service requests**, the administrator reviews it and chooses `low`, `medium`, `high`, or `urgent`. The employee can see that change in the activity history. Triage leaves the request status at `submitted`.

**Target repair lifecycle.** The administrator creates a work order and assigns a technician with access to the request's branch. The technician diagnoses the issue, records progress and repair actions, enters labor and material costs, and marks the work complete. The administrator verifies the result and closes the request, or returns it to active repair with an explanatory event. A request can have multiple work orders for follow-up repairs. Each work order has one technician. Request and maintenance histories preserve the actor and timestamp for traceability.

- Request states modeled in the schema: `submitted → in_progress → awaiting_verification → closed`.
- Work-order states modeled in the schema: `assigned → in_progress → completed`.
- The active API handles submission, priority changes, initial assignment, and starting work. Administrators assign a submitted request with no existing work order to an active technician with access to its branch. The work order starts as `assigned` and the request stays `submitted`. In **Assigned requests**, the assigned technician can see the work-order status and choose **Start work**. This changes both records to `in_progress` and adds an activity event in the same transaction.

**Delivery order from the development plan**

1. Append-only maintenance logs, labor and materials cost entry, and technician completion.
2. Verification, follow-up work orders, and administrator closure.
3. Asset registry management and protected photo uploads.
4. Branch dashboards, asset repair history, and cost summaries. Intended dashboard views cover open requests, ongoing repairs, completed work, and recorded costs.

**Future expansion.** Preventive maintenance scheduling, asset QR codes, email or SMS notifications, service targets and escalation, spare-parts inventory, purchase requests, external service providers, offline mobile capture and synchronization, and longer-term recurring-failure and replacement analysis.

## Authorization and activity rules

- The server enforces role and current branch grants. `branch_access` is explicit for all roles, including administrators. Revocation applies to subsequent protected calls even with an unexpired token.
- Employees can submit only to granted branches and see only their own requests in branches they can still access. Administrators see requests in their granted branches. Technicians need both current branch access and a linked work order assigned to them.
- Administrator account controls apply only to employees and technicians whose entire branch grant set is within the acting administrator's scope. Employees require exactly one branch. Technicians can have one or more. Administrators can grant only branches they already hold. Creating a branch grants the creator access. The current UI supports branch creation. Branch rename and deletion are outside the current interface.
- The first administrator can be provisioned through the browser with an optional setup token. Browser provisioning closes once an administrator exists. The bootstrap CLI can also provision administrators. The management API creates, reassigns and enables or disables employee and technician accounts. A disabled account cannot sign in or reuse an issued token. Accounts use Argon2 password hashing and expiring JWT bearer tokens with a 30-minute default. The React client keeps tokens in memory. Refresh requires sign-in, and client sign-out clears local session state while an issued token remains valid until expiry, subject to account and permission checks.
- Missing and out-of-scope request IDs return the same 404. A closed request returns 409 on reprioritization. Priority updates lock the request row and record an event only when the value changes. Submission and priority events commit in the same transaction as their corresponding changes. Keep future request events and maintenance logs append-only in application operations.
- Attachment files are intended to stay private. Enforce parent-request access on future downloads. The schema has attachment metadata, and the existing asset selector reads existing branch registry records. The baseline has no attachment transfer or asset registry management API.

## Architecture and data

The proposal groups the product into Core/User Management, Request Management, Work Order Management, Asset Management, Cost Tracking, and Reporting & Dashboard. Core supplies identity and branch access. Work orders build on requests, costs are recorded against work orders, and reporting reads operational records. These are product modules with a shared backend and database.

- **Frontend:** React, TypeScript and Vite with plain CSS. `frontend/src/main.tsx` owns sign-in, in-memory session state and workspace navigation. `Admin.tsx` renders People & branches, `Requests.tsx` renders reporting and triage, and `style.css` holds responsive styles.
- **Backend:** Python 3.14, FastAPI, Pydantic, SQLAlchemy and Alembic. `backend/app/main.py` wires the app and health, auth and branch routes. `security.py` handles tokens and current user checks. `admin.py` implements account and branch management. `requests.py` contains scoped queries, request payloads, event history and triage. `bootstrap.py` provisions an administrator with a privately prompted password.
- **Storage:** PostgreSQL 17, UUIDs, timezone-aware timestamps and decimal money fields. Schema changes go through Alembic. Server startup does not create tables or default accounts.

| Records | Relationships and decisions |
| --- | --- |
| `branches`, `users`, `branch_access` | A single user table represents all three roles. A join table grants branches. Users have a unique email, activation flag, and optional specialization. |
| `assets`, `service_requests` | Assets have a unique tag, branch and condition. Requests have a branch, submitter, location, nullable priority and optional asset. A composite foreign key enforces same-branch asset references. Closure fields capture who closed a request and when. |
| `work_orders`, `maintenance_logs` | A request may have many work orders. Each stores the technician and assigning user, work status, and separate nonnegative labor and materials costs. Maintenance logs store the recorder, action, notes, and timestamp. |
| `request_events`, `attachments` | Events store a request, actor, action, timestamp and structured details. Attachments store a parent request, uploader, storage key, original filename and content type. Photo bytes belong in private storage. |

The proposal's production topology is browser → HTTPS web gateway → FastAPI → private PostgreSQL, with a private volume for photos. The gateway serves the frontend and proxies `/api`. Separate branch subnets with site-to-site IPsec VPNs are an illustrative deployment option. Local development demonstrates the workflows on one computer. Production hardening still includes login throttling, session and recovery policy, secrets, HTTPS and reverse-proxy configuration, attachment validation, backups, and monitoring.

## API map

| Area | Available endpoints |
| --- | --- |
| Health and identity | `GET /api/health`, `GET /api/ready`, `POST /api/auth/login`, `GET /api/auth/me`, `GET /api/branches` |
| Initial setup | `POST /api/setup/admin` with `X-Setup-Token` when browser setup is enabled |
| Administrator | `POST /api/admin/branches`, `GET /api/admin/users`, `POST /api/admin/users`, `PUT /api/admin/users/{user_id}/branches`, `PATCH /api/admin/users/{user_id}/active` |
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
