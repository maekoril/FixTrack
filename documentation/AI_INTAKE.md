# AI request intake

The intake layer uses the existing FastAPI, React, SQLAlchemy, PostgreSQL, and Groq integration.
Analysis never creates a maintenance ticket. Reporters review suggestions and explicitly submit.

## API and flow

`POST /api/requests/triage` accepts authenticated branch managers and administrators with current
branch grants. Use JSON for text or multipart with `description`, optional `branch_id`,
`location_detail`, `conversation` (JSON string), and `image`. A conversation has at most two
rounds, each shaped as `{"answers":[{"question":"...","answer":"..."}]}` with up to three pairs.

The response envelope is `{result, triage_id, incomplete_info, manual_fallback, message,
safety_flags}`. `result` follows `TriageResult` in `app/triage_types.py`; it is null on manual
fallback. No ticket is created. The existing `POST /api/requests` accepts `triage_id`,
`category_id`, and `priority`. Submission rejects a snapshot from another account, different
source description/branch, reused snapshot, or unanswered follow-up state. Omitting the triage
ID permits manual submission. After two rounds, unresolved uncertainty sets **Incomplete info**
and allows human-confirmed submission. Short descriptions such as “sira po” are accepted.

The prompt contains the priority rubric, English/Tagalog/Taglish examples, and instructions to
ignore commands in reports and images. Pydantic validates enums, confidence, lengths, photo fields,
and question limits. Code fences are stripped before parsing. Known hazards are conservatively
checked locally; safety flags force the AI suggestion to urgent. People can still override it.
Confidence is not a calibrated probability, and photo analysis is not a technician inspection.

`PATCH /api/requests/{id}/triage-confirmation` accepts `{category, priority}`. Branch managers
can revise their own accessible reports and administrators their accessible reports, even after
closure. Normal work state, costs, and branch visibility do not change. Confirmed request fields
are authoritative; both this endpoint and existing administrator edits synchronize final values
and `ai_overridden`. `GET /api/requests?ai_overridden=true` supports scoped auditing. For accuracy
statistics, exclude manual records with `ai_category IS NULL`. Confirmation changes append history.

## Provider, privacy, and reliability

Text reports use `GROQ_MODEL`. Only reports with photos use `GROQ_VISION_MODEL`, default
`qwen/qwen3.8-27b`. Intake uses JSON-object output with the schema in the system prompt and local
validation. Text uses low reasoning effort; vision disables reasoning. Each attempt has a
15-second HTTP timeout. Provider/timeout/invalid-output failures get one retry, then manual
fallback. No valid provider response is required to submit manually. Groq model availability and
free-plan quotas can change. See [Groq vision documentation](https://console.groq.com/docs/vision).

Only report text, optional location, Q&A, and an optional cleaned photo are sent. Text strips
control characters/HTML, recognized emails, Philippine mobile numbers, and explicit name
introductions. Other personal details can remain in free text or photos. The UI discloses the
transfer. Account identities and branch names are not assembled into provider context.

Still JPEG/PNG/WebP intake photos are limited to 5 MB and 24 megapixels, checked against the
declared type, and re-encoded without EXIF into JPEG at most 1024 pixels on the longest side.
Pending draft image bytes are not retained; existing private photo upload follows ticket creation.
Invalid photos never reach the provider. Existing post-creation uploads retain their existing limits.

`intake_attempts` records account, time, outcome, and cumulative provider-reported prompt/completion
tokens, including invalid responses. User-row locks serialize rate reservations across workers;
`TRIAGE_REQUESTS_PER_MINUTE` defaults to 5, including failed attempts. Manual submission is
unaffected. Usage logs contain only IDs, outcome, and counts. Failed provider bodies are neither
logged nor saved. `request_intakes` preserves a validated parsed source response for debugging,
not raw HTTP bodies; source JSON is not returned to clients.

Safety flags highlight queue/details and create an inbox event in the submission transaction.
The reporting branch manager receives it even when also the event's actor. Other branch managers
do not gain access to that report. Current access checks and the existing five-second poll apply.

## Schema and taxonomy

Migration `e40d51a6b902` adds intake snapshots and attempt records, and seeds Carpentry,
Civil & Structural, Pest Control, and Cleaning & Sanitation. Original/normalized descriptions,
language, AI category/subcategory/priority/reason/safety/confidence, photo observations, final
values, overrides, Q&A, incomplete state, validated response, and creation time are preserved.
Manual intake leaves AI routing values null. Downgrade retains seeded categories to preserve
existing references; seeds are idempotent on re-upgrade.

The ten intake categories map to registry IDs in `CATEGORY_IDS`. Existing registry entries are
reused. Building & Facilities remains a legacy registry option. To change taxonomy, update the
literal/map in `triage_types.py`, add a seed migration, update `intakeCategories` in the frontend,
and update sample fixtures and tests. The prompt/schema are generated from these definitions.

## Validation

From `backend/`, run `.venv/Scripts/python -m pytest -q`, Ruff checks, and `alembic check`.
From `frontend/`, run `npm run build`. The automated suite mocks provider calls. Samples live in
`backend/tests/fixtures/intake_samples.json`: English, Tagalog, Taglish, vague, hazard, and injection.
Live checks use those synthetic inputs and a generated illustration, never production reports.

For a browser check, report “sira po”, answer two question rounds, and verify no ticket exists
before confirmation. Review a socket-spark report, override priority, submit, and check that both
AI/final values and the safety alert remain. Check that the saved description is readable, routing
controls and AI notes are hidden until **Edit**, and Cancel discards unsaved changes. Save a category
or priority change and verify the summary updates. Use the plus tile beside request photos to add
an image and verify upload feedback. Remove the
Groq key and restart to verify manual submission still works. Select an invalid or oversized photo
to verify rejection; check a valid photo preview and AI observations. Revoke a user's branch grant
to verify subsequent protected actions are rejected.

## Files changed for intake

- Backend: `app/intake.py`, `app/triage_types.py`, `app/triage_prompt.py`, `app/models.py`,
  `app/requests.py`, `app/notifications.py`, `app/main.py`, `app/config.py`.
- Schema/config: `migrations/versions/e40d51a6b902_ai_request_intake.py`, `requirements.in`,
  `requirements.txt`, `.env.example`.
- Frontend: `src/RequestIntake.tsx`, `src/Requests.tsx`, `src/Notifications.tsx`, `src/workspace.css`.
- Tests: `tests/test_intake.py`, `tests/fixtures/intake_samples.json`, `tests/test_requests.py`.
- Docs: `README.md`, `documentation/MASTER_CONTEXT.md`, `documentation/DEVELOPMENT.md`, this file.
