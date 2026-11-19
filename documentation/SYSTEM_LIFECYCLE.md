# FixTrack lifecycle and debugging guide

Reviewed November 19, 2026 against the current checkout. Read alongside
[Master Context](MASTER_CONTEXT.md) and [Development](DEVELOPMENT.md).

## Administrator prepares the organization

Provision the first administrator through guarded setup or the bootstrap CLI. Create branches,
branch managers, and technicians in People & branches. Grant branch access explicitly to every
role, including administrators. Set optional technician specializations and register equipment
in Assets. General facility reports do not require a registered asset.

An administrator manages accounts only when all their branch grants fall within that admin's
own scope. Disable accounts with recorded activity instead of deleting them. Disabled accounts
cannot reuse issued tokens. A manager or technician requires at least one branch.

## Branch manager reports

Choose an accessible branch, title, description, location, optional asset, and optional photos.
AI intake can normalize English/Tagalog/Taglish descriptions, suggest category/priority, flag
safety concerns, and ask limited follow-ups. The manager reviews the routing before submission.
Manual intake remains available. Analysis alone never creates a request.

Submission creates a `submitted` request and activity record and alerts scoped administrators.
Managers see only their own reports in branches they can currently access, not all branch reports.

## Administrator reviews and plans

Review description, safety flags, incomplete-information indicators, photos, and asset context.
Confirm priority/category and set difficulty and duration. Priority is urgency; difficulty is
repair complexity. Request setup saves these values together with lead/supporting technicians,
schedule, and price estimate. Partial saves identify remaining setup fields.

Assignment creates an `assigned` work order; the request remains `submitted` until the lead
starts. Team members must be active technicians with branch access. Schedule conflicts include
leads and assistants across branches. Changing service duration leaves existing appointments fixed.

AI estimates use saved details and propose duration, tasks, material quantities, assumptions,
and questions. They provide no prices. Copying duration/materials edits the form; Save setup
is still required. Generated tasks and assumptions are temporary and are not automatically
saved as technician instructions. Supply verified material unit prices and price sources.

Labor estimate = hourly rate per technician × duration in hours × team size. Add material
subtotals rounded individually to cents. A manual total requires a reason. Saving creates a
versioned draft. Approve estimate separately preserves an approved snapshot. Later draft edits
leave the previous approval intact until the replacement is approved.

## Technician executes

The assigned lead chooses Start work, changing request and order to `in_progress`. Scheduling
does not start work automatically. The lead and supporting technicians can add maintenance
actions, diagnosis/progress/repair notes, and repair photos while the order is in progress.

Only the lead can submit completion, entering actual labor and material costs. Actual costs
above the last approved budget require an explanation. Completion marks the order `completed`,
changes the request to `awaiting_verification`, and alerts administrators. Technicians cannot
verify or close requests. Managers track status, appointments, maintenance notes, and activity;
private costs and budget events are excluded from their view.

## Administrator verifies or returns

Review the latest completed order's logs, photos, actual costs, and overrun explanation.

- Verify and close sets the request to `closed` and records the reviewer and time.
- Return for follow-up requires instructions and an eligible team. It preserves the completed
  order, creates a new `assigned` order, and returns the request to `in_progress`.
- The new lead must still start the new order before recording repair entries. Plan its own
  schedule and budget; prior appointments and approvals are not automatically transferred.
- Repeat completion/review until closure. Stale review actions targeting an older order fail.

Managers see the follow-up or closure decision in history. There is no manager acceptance step
or normal reopen action for closed requests. A new issue can reference the same asset.

## Reporting and access

Reports count verified closures by closure date and completed orders by completion date,
including follow-ups. Costs are actuals. One request can contribute several completed orders
and one closure. Report filters use inclusive UTC days; timestamps display in local formatting.

Visible queues, inbox, dashboard, and selected requests refresh every five seconds. Protected
calls recheck current branch grants and account activation. Sign-out clears the browser session;
issued tokens otherwise remain valid until expiry (30 minutes by default).

## Review findings

| Finding | Change | Verification |
| --- | --- | --- |
| Assistant showed all sections and repeated instructions | Compact summary/actions, expandable materials/tasks/questions/assumptions and full data disclosure | Regular and 375px content-width browser preview |
| Regeneration discarded a usable plan before replacement succeeded | Keep prior plan and copied-item state on failure | Simulated failure after copying duration and materials |
| CORS omitted DELETE despite account deletion support | Allow DELETE for configured origins | Allowed/rejected-origin preflight regression |
| Setup matching used strict text equality | Normalize specialization spacing/capitalization | Frontend matching regression |

## Policy decisions and remaining scope

- **Setup and approval are advisory:** starting before complete setup and completing without
  an approved budget are allowed. Setup complete does not mean budget approved.
- **Completion evidence is optional:** the API does not require a log or repair photo before
  completion. Reviewers assess evidence; AI does not verify repairs.
- **AI plans are temporary:** save the relevant planning values and communicate instructions
  explicitly. Technicians do not automatically receive the generated plan.
- **Closure belongs to administrators:** managers cannot accept/reject or reopen repairs.
- **Technician asset history remains planned:** admins have asset history; technicians see
  their assigned requests/orders.
- **Production hardening remains planned:** see Development for login throttling, password
  recovery, token/logout policy, HTTPS, backups, and monitoring.

These are existing behaviors to evaluate during operational acceptance. This review does not
silently introduce mandatory approvals, evidence requirements, or new role permissions.

## Validation and repeatable acceptance

This review passed 111 backend tests, backend Ruff lint/format checks, the frontend build,
and five frontend planning tests. Backend tests use SQLite and mocked AI providers, so they
do not establish PostgreSQL concurrency behavior or live Groq output quality.

Use disposable local records for a browser acceptance pass:

1. Create/grant a manager and two technicians; keep another branch inaccessible.
2. Report manually and via AI. Confirm analysis creates no request and another manager
   cannot open the report.
3. Save partial setup, then assign/schedule/price/save/approve. Try an overlapping schedule
   and stale approval; rejected saves must leave no partial changes.
4. Start as lead. Add a log/photo as support; start/completion as support must fail. Submit
   actual costs above budget with and without an explanation.
5. Return for follow-up; plan/start/complete the new order and close it. Old logs and costs
   must remain, and an old review action must not close the new cycle.
6. Check manager visibility, private-cost filtering, inbox, reports including both orders,
   and immediate loss of access after branch-grant revocation.
7. Separately test PostgreSQL concurrent saves, real provider failure/recovery, and target
   mobile browsers. The isolated UI preview used fixtures and no paid AI calls.
