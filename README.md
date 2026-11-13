# FixTrack

A multi-branch maintenance and service request system for reporting issues, assigning repairs,
recording actions and costs, and verifying resolution.

Start with the [FixTrack Master Context](documentation/MASTER_CONTEXT.md) for product scope,
role and branch rules, implementation status, and the roadmap.

**Status:** authentication, administrator account/branch controls, employee service requests,
branch-scoped request review, priority changes, initial work-order assignment, starting repairs,
and activity history are implemented. Repair logs and costs, closure, and photo uploads are upcoming.

## Repository layout

```text
backend/          FastAPI, SQLAlchemy models, Alembic migrations, tests
frontend/         React + TypeScript + Vite
documentation/    Original proposal and development architecture
.github/          CI, issue templates, and pull request template
compose.yaml      Local PostgreSQL database
```

## Prerequisites

- Python 3.14
- Node.js 24 LTS and npm
- Docker Desktop with Compose, or PostgreSQL 17 installed locally
- Git

## Local setup (PowerShell)

From the project root, start PostgreSQL:

```powershell
docker compose up -d db
```

The Compose credentials are for local development and bind only to localhost. An existing
PostgreSQL installation works too: create a database/user and adjust `DATABASE_URL` below.

Set up the API:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into `JWT_SECRET` in `backend/.env`, replacing the placeholder.
Run the generator again and add the new value as `SETUP_TOKEN` in the same file.
Apply migrations and start the API:

```powershell
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1
```

Open a second terminal at the project root:

```powershell
cd frontend
npm ci
npm run dev
```

Open [First administrator setup](http://localhost:5173/#setup), enter your `SETUP_TOKEN`,
and create the account and its initial branch. Then sign in with the new account.
Browser setup closes once an administrator exists. Remove `SETUP_TOKEN` from `backend/.env`
and restart the API after setup. The `python -m app.bootstrap` CLI remains available for
provisioning additional administrators.
The Vite development server proxies `/api` to FastAPI. API documentation is at
[Swagger UI](http://127.0.0.1:8000/docs). Run backend commands from `backend/` so `.env` is found.
On macOS/Linux, use `.venv/bin/python` in place of `.venv\Scripts\python`.

## Try the request workflow

1. Sign in as an administrator and open **People & branches**.
2. Create an employee account with access to one of your branches.
3. Sign out and sign in as that employee. Select **Report an issue**, fill in its title,
   description, and location, then submit it. A registered asset is optional.
4. Sign in as the administrator again. Open the request under **Service requests** and set
   its priority. The employee can see the update in the request's activity history.
5. On the request detail page, select an active technician with access to the branch and choose
   **Assign technician**. Sign in as that technician and open **Assigned requests** to see it.
6. Open the assigned request and choose **Start work**. Both the work order and the request
   move to **In progress**, and the request history records who started the work.

Employees see their own requests within their current branch access. Administrators see all
requests in their branches. Technicians see requests linked to their assigned work orders;
their branch access still applies. A submitted request can receive one initial work order.
It stays `submitted` after assignment and the work order starts as `assigned`.

## Checks and migrations

```powershell
cd backend
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m alembic check
# After changing models, review the generated migration before committing it:
.venv\Scripts\python -m alembic revision --autogenerate -m "describe schema change"
.venv\Scripts\python -m alembic upgrade head
cd ../frontend
npm run build
```

Backend dependencies are pinned in `requirements.txt`; `requirements.in` records the direct
dependency intent. Regenerate pins in a clean Python 3.14 environment when deliberately upgrading.
Frontend dependencies are locked in `package-lock.json`; collaborators should use `npm ci`.

## Upload to GitHub

Create an **empty** repository on GitHub (without a generated README, license, or `.gitignore`).
Then run from the project root, replacing the URL with your repository URL:

```powershell
git add .
git diff --cached --stat
git commit -m "chore: initialize FixTrack development foundation"
git remote add origin https://github.com/YOUR-TEAM/FixTrack.git
git push -u origin main
```

Before committing, confirm no `.env` or private data is staged. Invite collaborators and configure
the `main` branch rules described in [CONTRIBUTING.md](CONTRIBUTING.md).
Git is initialized locally; no GitHub repository is created or published by setup.

Read [the development notes](documentation/DEVELOPMENT.md) for schema decisions and milestones,
and the [project proposal](documentation/FixTrack_Project_Proposal.pdf) for the original scope.
