# Contributing to FixTrack

1. Pick or create an issue with clear acceptance criteria. Agree on ownership before editing shared modules.
2. Branch from `main`: `feat/request-submission`, `fix/login-error`, or `docs/setup`.
3. Keep each pull request focused. Commit source, lockfiles, and migrations together.
4. Run the checks below and explain the results in the pull request. Include UI screenshots when relevant.
5. Ask another teammate to review. Resolve feedback and squash merge after CI passes.

```powershell
cd backend
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m pytest -q
cd ../frontend
npm ci
npm run build
```

Use `python -m ruff check . --fix` and `python -m ruff format .` for backend formatting.
Never commit passwords, signing keys, `.env`, database dumps, or issue photos.
Do not edit an applied migration; add a new revision. Coordinate migration heads before merging.
All future API handlers must enforce both role permissions and branch access on the server.
Keep request and maintenance histories append-only through application operations.

The repository owner should enable a ruleset for `main`: require pull requests, one review,
resolved conversations, and both CI jobs. Block force pushes and branch deletion.
Add a `CODEOWNERS` file once team GitHub handles and responsibilities are known.
A license must be agreed by the project owner/team before adding a license file.
