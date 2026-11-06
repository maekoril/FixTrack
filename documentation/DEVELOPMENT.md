# Development architecture and milestones

## Foundation decisions

- React + TypeScript + Vite frontend; FastAPI + SQLAlchemy backend; PostgreSQL 17 database.
- UUID primary keys, UTC timestamps, and decimal money fields.
- One user table with employee, technician, and administrator roles. `branch_access` grants
  explicit access to branches for every role. Employees should normally have one assigned branch.
- Assets and service requests belong to a branch. A composite foreign key prevents a request
  from referencing an asset from another branch. General facility requests need no asset.
- A request can have multiple work orders. Each work order has one technician, labor and material
  costs, and maintenance logs. Request events record the actor and changes.
- Attachment metadata is modeled; uploads and downloads are not implemented yet. Files will
  stay private, and download handlers must enforce the parent request's access rules.
- Passwords use Argon2; short-lived signed bearer tokens identify the current user. Account
  activation and current permissions are read from the database on protected requests.
- The initial frontend uses the token only during sign-in to load profile and branches and then
  discards it. Refresh requires signing in again. Future authenticated tools should use an
  in-memory session provider. Do not persist bearer tokens in localStorage.
- No public registration, default accounts, or automatic schema creation at server startup.

## Implemented endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Process liveness |
| `GET /api/ready` | Database connectivity |
| `POST /api/auth/login` | JSON email/password to expiring bearer token |
| `GET /api/auth/me` | Authenticated profile |
| `GET /api/branches` | Branches explicitly granted to the current user |

## Next milestones

1. Administrator user/branch management: create users, grant branch access, disable accounts.
2. Employee request submission/list/detail; optional assets and protected photo uploads.
3. Administrator priority and work-order assignment; verify technician role and branch access.
4. Technician progress, immutable maintenance history, and cost entry.
5. Completion verification, follow-up work orders, and administrator closure.
6. Branch dashboards, asset repair history, and cost summaries.

Proposed request states: `submitted -> in_progress -> awaiting_verification -> closed`.
An administrator may return a repair to `in_progress` with an explanatory event.
Work orders use `assigned -> in_progress -> completed`. Transition validation and transactional
event writes belong in the workflow service when these endpoints are implemented.

## Before production

This is a development foundation. Add login throttling, a reviewed session/logout and password
recovery policy, deployment secrets, HTTPS/reverse proxy configuration, attachment validation,
backups, and operational monitoring before a public deployment. A client sign-out currently
clears the displayed session; issued API tokens expire after 30 minutes and are not revoked by it.

CI applies, checks, rolls back, and reapplies migrations against PostgreSQL. The fast auth and
constraint tests use SQLite with foreign keys enabled; extend PostgreSQL integration coverage
as transactional workflows are added.
