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

Administrator tools manage only branch managers and technicians whose complete branch access is
within the administrator's scope. Both roles may have multiple branches.
Administrators cannot grant branches they do not have. Administrator accounts are
provisioned through the first-admin browser setup or the bootstrap CLI. These management endpoints can only create or disable branch managers and technicians.
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

1. Expanded asset reporting and cost summaries.

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

This is a development foundation. Add login throttling, a reviewed session/logout and password
recovery policy, deployment secrets, HTTPS/reverse proxy configuration, attachment validation,
backups, and operational monitoring before a public deployment. A client sign-out currently
clears the displayed session; issued API tokens expire after 30 minutes and are not revoked by it.

CI applies, checks, rolls back, and reapplies migrations against PostgreSQL. The fast auth and
constraint tests use SQLite with foreign keys enabled; extend PostgreSQL integration coverage
as transactional workflows are added.
