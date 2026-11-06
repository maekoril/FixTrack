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
| `GET/POST /api/admin/users` | List managed users or create employee/technician accounts |
| `PUT /api/admin/users/{id}/branches` | Replace a managed user's branch access |
| `PATCH /api/admin/users/{id}/active` | Disable or enable a managed account |

Administrator tools manage only employees and technicians whose complete branch access is
within the administrator's scope. Employees require exactly one branch; technicians may have
several. Administrators cannot grant branches they do not have. Administrator accounts are
provisioned through the bootstrap CLI, so these endpoints cannot create or disable administrators.
Creating a new branch grants the creator access. The current interface lets administrators
create branches but does not rename or remove existing branches.

## Next milestones

1. Employee request submission/list/detail; optional assets and protected photo uploads.
2. Administrator priority and work-order assignment; verify technician role and branch access.
3. Technician progress, immutable maintenance history, and cost entry.
4. Completion verification, follow-up work orders, and administrator closure.
5. Branch dashboards, asset repair history, and cost summaries.

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
